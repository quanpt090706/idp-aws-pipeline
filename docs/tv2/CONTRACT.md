# TV2 contract triển khai — 1.0

Đây là contract dùng để code/test TV2 theo lựa chọn đã được người phụ trách TV2 chấp thuận.
TV1/TV4/TV5 cần xác nhận khi ghép hệ thống; không đồng nghĩa mọi thành viên đã duyệt Giai đoạn 0.

| Nội dung | Quy ước |
| --- | --- |
| Upload key | `uploads/{user_id}/{document_id}/{file_name}`, tên file không có slash/backslash/control char, tối đa 255 ký tự |
| ID | 1–64 ký tự ASCII chữ/số/underscore/hyphen; TV1 tạo document_id mới mỗi lần upload |
| Loại file | PDF/JPG/JPEG/PNG, không phân biệt hoa thường; magic bytes khớp đuôi |
| Kích thước demo | 1–10485760 byte (10 MiB); giới hạn cấu hình được ở Validate |
| Loại tài liệu | `INVOICE` hoặc `TRANSCRIPT` từ Documents do API TV1 tạo |
| DynamoDB key | `PK=USER#{user_id}`, `SK=DOC#{document_id}`, đọc strongly consistent |
| Chuyển trạng thái TV2 | Chỉ `UPLOAD_PENDING → QUEUED/REJECTED`, update có điều kiện |
| Bản ghi TV1 tạo | user_id, document_id, file_name, document_type, status, created_at, updated_at; nên có s3_key đúng key đã ký |
| Trường QUEUED | size_bytes, content_type, s3_key, object_etag, queued_at, updated_at |
| Trường REJECTED | reject_reason, reject_detail, rejected_at, updated_at |
| Retry chủ động | Chỉ attempt=1; redrive không tăng attempt |
| State machine | Standard; TV4 đổi QUEUED → PROCESSING có điều kiện, giữ trường ingestion |

Đuôi file lấy từ dấu chấm cuối cùng, thống nhất ở Validate và Starter;
ví dụ `.pdf`/`..PDF` vẫn có đuôi `.pdf`, chỉ được chấp nhận khi nội dung qua kiểm tra.
Đây là quy tắc hiện có được giữ nhất quán, không bổ sung định dạng file mới.

Mẫu SQS body nằm ở `tests/fixtures/sqs_message.json`, input workflow ở
`tests/fixtures/step_functions_input.json`. Đây là dữ liệu giả,
không phải mẫu đã thu từ AWS. Body gồm schema_version, document_id, user_id, document_type,
bucket, key đã decode, file_name, content_type, size_bytes, etag, attempt, request_id, queued_at.

Starter chỉ nhận `schema_version="1.0"`, đối chiếu bucket/key và trường Documents.
Input Step Functions bỏ request_id/queued_at, chỉ lấy 11 trường ổn định trong `app.INPUT_FIELDS`,
serialize theo sort_keys. Tên execution là `doc-` + 32 ký tự đầu SHA256 của JSON
`[user_id, document_id, attempt]`. Cùng tên khác input không được coi là duplicate thành công.

`UPLOAD_PENDING`/thiếu record: retry SQS, chưa StartExecution.
`QUEUED`: gọi StartExecution. `PROCESSING/SUCCEEDED/NEEDS_REVIEW/FAILED`:
chỉ xác minh execution cũ có cùng input, không tạo mới.
`REJECTED`/status lạ/message không khớp: partial failure → DLQ sau maxReceiveCount.

Mã reject: UNSUPPORTED_EXTENSION, FILE_EMPTY, FILE_TOO_LARGE, CONTENT_MISMATCH,
INVALID_DOCUMENT_TYPE. UI TV1 map reason sang thông báo; không dùng reject_detail làm log công khai.
Hệ thống runtime còn cần IAM phù hợp; contract key không tự chứng minh quyền sở hữu người dùng.

Không thay mô hình JobCallbacks/parser/API của TV3/TV4 trong phần triển khai TV2.
