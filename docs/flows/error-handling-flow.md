# Luồng Xử lý Lỗi

Mô tả cách hệ thống xử lý các trường hợp lỗi ở từng bước trong pipeline — từ file không hợp lệ đến Textract thất bại.

> Một hệ thống chuyên nghiệp không chỉ hoạt động được ở "happy path" mà phải xử lý được lỗi một cách có kiểm soát, không làm mất dữ liệu.

---

## Các loại lỗi và cách xử lý

### Loại 1 — File không hợp lệ (Lambda Validate)

```mermaid
flowchart TD
    A[S3 Event: File mới upload] --> B[Lambda Validate]
    B --> C{Kiểm tra file}

    C -->|Định dạng sai\nvd: .exe, .zip| D[Ghi log lỗi]
    C -->|Kích thước > 500MB| D
    C -->|File bị corrupt| D
    C -->|Hợp lệ| E[Đẩy vào SQS Queue chính]

    D --> F[Đẩy vào Dead Letter Queue]
    F --> G[CloudWatch ghi metric\nlỗi validation tăng]
    G --> H{Vượt ngưỡng\nalarm?}
    H -->|Có| I[CloudWatch Alarm\ngửi SNS alert cho admin]
    H -->|Không| J[Chờ admin review thủ công]
```

---

### Loại 2 — Textract thất bại (Step Functions retry)

```mermaid
sequenceDiagram
    participant SFN as Step Functions
    participant LambdaS as Lambda – Start Job
    participant Textract as Amazon Textract
    participant DLQ as Dead Letter Queue
    participant CW as CloudWatch

    SFN->>LambdaS: Thực thi StartJob (lần 1)
    LambdaS->>Textract: StartDocumentAnalysis(...)
    Textract-->>LambdaS: ThrottlingException (quá nhiều job)

    Note over SFN: Retry lần 2 sau 2 giây (exponential backoff)
    SFN->>LambdaS: Thực thi StartJob (lần 2)
    LambdaS->>Textract: StartDocumentAnalysis(...)
    Textract-->>LambdaS: ThrottlingException

    Note over SFN: Retry lần 3 sau 4 giây
    SFN->>LambdaS: Thực thi StartJob (lần 3)
    LambdaS->>Textract: StartDocumentAnalysis(...)
    Textract-->>SFN: Thành công / Vẫn lỗi

    alt Vẫn thất bại sau 3 lần retry
        SFN->>DLQ: Đẩy message kèm context lỗi
        SFN->>CW: Ghi execution lỗi
        CW->>CW: Trigger CloudWatch Alarm
    end
```

---

### Loại 3 — Parse thất bại (Textract trả kết quả không đọc được)

```mermaid
flowchart LR
    A[Lambda Parse nhận kết quả Textract] --> B{Parse thành công?}

    B -->|Có| C[Lưu DynamoDB + S3 + Gửi SES]

    B -->|Không - thiếu trường bắt buộc| D[Lưu raw JSON vào S3\nvới flag needs_review]
    D --> E[Ghi trạng thái FAILED vào DynamoDB]
    E --> F[Gửi email admin\nkèm link file gốc]

    B -->|Không - JSON Textract bị lỗi| G[Throw exception]
    G --> H[Step Functions bắt exception\nchuyển sang Catch state]
    H --> D
```

---

## Bảng tóm tắt chiến lược xử lý lỗi

| Loại lỗi | Nơi xảy ra | Chiến lược | Hành động |
|---|---|---|---|
| File sai định dạng / kích thước | Lambda Validate | Fail fast | Đẩy DLQ, ghi log |
| Throttling từ Textract | Step Functions | Retry + exponential backoff | Tối đa 3 lần, sau đó DLQ |
| Textract job FAILED | SNS → Lambda Parse | Catch và escalate | Ghi DynamoDB, alert admin |
| Parse không đọc được trường | Lambda Parse | Degrade gracefully | Lưu raw JSON, flag manual review |
| Lambda timeout | Step Functions | Catch state | Đẩy DLQ, CloudWatch Alarm |

---

## Dead Letter Queue — "Phòng cách ly" file lỗi

DLQ không phải thùng rác — đây là nơi lưu tạm **có thể xử lý lại** sau:

```
DLQ message chứa:
- s3_key: đường dẫn file gốc
- error_reason: lý do thất bại
- retry_count: đã thử bao nhiêu lần
- timestamp: thời điểm lỗi
```

Admin có thể vào DLQ, kiểm tra message, sửa vấn đề (ví dụ: tăng quota Textract) rồi **redrive** (đẩy lại vào queue chính) mà không cần người dùng upload lại file.
