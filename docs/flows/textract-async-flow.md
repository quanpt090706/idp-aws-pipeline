# Luồng Xử lý Textract Async

Mô tả chi tiết luồng từ khi message ra khỏi SQS đến khi kết quả được lưu vào database và người dùng nhận email thông báo.

> Đây là phần phức tạp nhất của pipeline và hay bị hỏi nhất trong vấn đáp. Điểm mấu chốt: Textract **không trả kết quả ngay** (async) — hệ thống dùng SNS callback thay vì polling mỗi giây.

---

## Sequence Diagram

```mermaid
sequenceDiagram
    participant SQS as SQS Queue
    participant SFN as Step Functions
    participant LambdaS as Lambda – Start Job
    participant Textract as Amazon Textract
    participant SNS as SNS Topic
    participant LambdaP as Lambda – Parse
    participant DDB as DynamoDB
    participant S3R as S3 Processed
    participant SES as Amazon SES
    participant CW as CloudWatch

    SQS->>SFN: Trigger state machine (s3_bucket, s3_key, user_id)

    Note over SFN,Textract: Bước 1 – Khởi động Textract job
    SFN->>LambdaS: Thực thi bước StartJob
    LambdaS->>Textract: StartDocumentAnalysis(s3_key, SNS_topic_arn)
    Textract-->>LambdaS: job_id
    LambdaS-->>SFN: Trả job_id → chuyển sang trạng thái Wait

    Note over SFN: ⏳ Step Functions dừng lại, giữ nguyên trạng thái
    Note over SFN: Không polling, không tốn tài nguyên

    Note over Textract,LambdaP: Bước 2 – Textract xử lý xong, gọi lại hệ thống
    Textract->>SNS: Publish notification (job_id, status=SUCCEEDED/FAILED)
    SNS->>LambdaP: Trigger Lambda Parse với job_id

    Note over LambdaP,S3R: Bước 3 – Parse và lưu kết quả
    LambdaP->>Textract: GetDocumentAnalysis(job_id)
    Textract-->>LambdaP: Raw JSON (Blocks: KEY_VALUE_SET, TABLE, LINE...)

    LambdaP->>LambdaP: Trích xuất các trường (vendor, total_amount, date, items...)
    LambdaP->>DDB: Lưu structured data (các trường đã parse)
    LambdaP->>S3R: Lưu raw JSON Textract (file lớn, không nhét vào DynamoDB)
    LambdaP->>SES: Gửi email thông báo kèm link xem kết quả
    LambdaP->>SFN: Gửi task token callback (success)

    Note over SFN: Bước 4 – State machine kết thúc thành công
    SFN->>CW: Ghi log execution (duration, status)

    alt Textract trả về FAILED
        Textract->>SNS: Publish notification (status=FAILED)
        SNS->>LambdaP: Trigger với status FAILED
        LambdaP->>SFN: Gửi task token callback (failure)
        SFN->>SFN: Thực hiện retry theo cấu hình
        SFN->>CW: Ghi log lỗi, trigger CloudWatch Alarm
    end
```

---

## Tại sao dùng Async API thay vì Sync API?

| | Sync (`AnalyzeDocument`) | Async (`StartDocumentAnalysis`) |
|---|---|---|
| **Giới hạn trang** | Tối đa 1 trang | Không giới hạn |
| **Kích thước file** | Tối đa 5 MB | Tối đa 500 MB |
| **Thời gian chờ** | Lambda phải chờ trong suốt quá trình | Lambda trả về ngay sau khi gửi job |
| **Chi phí** | Trả per-page, block Lambda | Hiệu quả hơn cho file nhiều trang |
| **Phù hợp** | Demo đơn giản, 1 trang | Production, file thực tế |

---

## Vai trò của Step Functions

Step Functions giữ **trạng thái** của toàn bộ pipeline qua các bước:

```
[Start] → StartJob → WaitForCallback → ParseResult → [End]
                           ↑
                    SNS callback làm
                    State machine tiếp tục
```

Nếu không có Step Functions và dùng Lambda gọi nhau trực tiếp:
- Khi Lambda B timeout không ai biết pipeline đang ở bước nào
- Không có retry tự động
- Không có log từng bước để debug
