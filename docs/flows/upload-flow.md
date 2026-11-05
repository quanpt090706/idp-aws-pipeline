# Luồng Upload File

Mô tả chi tiết luồng từ khi người dùng truy cập giao diện đến khi file được đưa vào hàng đợi xử lý.

> Diagram tổng quan ở README chỉ thể hiện *ai kết nối với ai*. Diagram này thể hiện *thứ tự thời gian* và *dữ liệu truyền qua từng bước*.

---

## Sequence Diagram

```mermaid
sequenceDiagram
    actor User as User (Nhân viên kế toán)
    participant CF as CloudFront
    participant S3Web as S3 Static Website
    participant APIGW as API Gateway
    participant Cognito as Cognito User Pool
    participant LambdaURL as Lambda – Presigned URL
    participant S3Up as S3 Upload Bucket
    participant LambdaV as Lambda – Validate
    participant SQS as SQS Queue

    Note over User,S3Web: Bước 1 – Tải giao diện web
    User->>CF: Truy cập URL ứng dụng
    CF->>S3Web: Lấy HTML/CSS/JS (từ cache nếu có)
    S3Web-->>User: Trả về giao diện

    Note over User,Cognito: Bước 2 – Đăng nhập
    User->>APIGW: POST /auth (email + password)
    APIGW->>Cognito: Xác thực credentials
    Cognito-->>User: JWT Access Token (hạn 1 giờ)

    Note over User,LambdaURL: Bước 3 – Lấy presigned URL
    User->>APIGW: POST /upload-url (JWT Token, tên file)
    APIGW->>Cognito: Verify JWT Token
    APIGW->>LambdaURL: Sinh presigned URL cho file này
    LambdaURL-->>User: Presigned URL (hết hạn sau 15 phút)

    Note over User,S3Up: Bước 4 – Upload trực tiếp lên S3 (không qua server)
    User->>S3Up: HTTP PUT file (PDF/JPG/PNG) dùng presigned URL
    S3Up-->>User: 200 OK

    Note over S3Up,SQS: Bước 5 – Trigger tự động vào pipeline
    S3Up->>LambdaV: S3 Event (ObjectCreated)
    LambdaV->>LambdaV: Kiểm tra định dạng + kích thước file
    alt File hợp lệ
        LambdaV->>SQS: Đẩy message (s3_bucket, s3_key, user_id)
        SQS-->>LambdaV: Message ID xác nhận
    else File không hợp lệ
        LambdaV->>SQS: Đẩy vào Dead Letter Queue
    end
```

---

## Giải thích các quyết định thiết kế

| Quyết định | Lý do |
|---|---|
| **Presigned URL thay vì upload qua Lambda** | Lambda phải đọc toàn bộ file vào RAM nếu làm proxy → chậm, tốn tiền. Presigned URL cho phép client upload thẳng lên S3, Lambda chỉ tạo link rồi "ngủ" |
| **CloudFront đứng trước S3 Static** | Cache file tĩnh tại edge server gần người dùng nhất, giảm latency và chi phí băng thông S3 |
| **SQS thay vì Lambda gọi thẳng** | Buffer chống tải đột biến: 500 người upload cùng lúc → 500 message vào queue, Lambda consume từng batch thay vì 500 Lambda chạy song song |
| **Lambda Validate trước SQS** | Lọc file rác sớm, không để file không hợp lệ chiếm chỗ trong queue và lãng phí Textract credit |
