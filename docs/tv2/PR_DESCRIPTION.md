# Implement TV2 ingestion and workflow starter

Repository chỉ có placeholder Lambda/test. Thay bằng Validate kiểm tra PDF/JPG/PNG, cập nhật Documents
QUEUED/REJECTED có điều kiện, gửi SQS và Workflow Starter có kiểm tra schema, trạng thái,
input/tên execution xác định và partial batch response.

Ví dụ: SQS tới khi Documents còn UPLOAD_PENDING được retry; chỉ khi QUEUED mới start Standard workflow.
Event/message lặp dùng cùng execution; input mâu thuẫn không được ack như duplicate.
So sánh input cũ phân biệt `true`, `1` và `1.0`, vẫn chấp nhận khác whitespace/thứ tự trường.
SQS escape U+FFFE/U+FFFF để giữ nguyên key sau decode; ba fixture cùng mô tả object `hóa đơn.pdf`.

Kèm dependency/ZIP build, preflight đọc-only, smoke test dev có account guard,
Terraform module và dev scaffold sử dụng role Academy có sẵn, alarm và runbook từng Bước 0–13.

Preflight xác minh PK/SK kiểu String và notification không lọc suffix để mọi upload đều tới Validate.
Mọi mapping SQS liên quan đang bật phải có partial batch; visibility gồm 6 lần timeout Lambda và batch window lớn nhất.
IAM StartExecution dùng ARN workflow gốc với qualifier condition cho alias/version.
Root dev yêu cầu Terraform >= 1.11 cho các test có plan-time override.
Alarm lỗi/hàng lỗi dùng 1 trong 2 kỳ vượt ngưỡng; alarm backlog giữ 2 kỳ.

Starter thống nhất cách lấy đuôi file với Validate, kể cả tên `.pdf`/`.jpg`/`.png`.
Preflight chặn MAX_FILE_SIZE_BYTES sai hoặc lệch giới hạn demo 10485760 byte.
Smoke kiểm tra đủ 11 trường input theo tên/kiểu/giá trị và lấy ETag kỳ vọng từ response upload;
báo cáo chỉ xác nhận ingestion, không xác nhận OCR. Probe đọc hết IAM roles và phân tích trust policy
để tách ứng viên với trường hợp cần kiểm tra, không khẳng định quyền IAM hiệu lực.
Smoke quan sát hết cửa sổ cấu hình sau upload, kết thúc bằng lượt quét bắt đầu tại/sau deadline,
giữ lỗi đã thấy và ghi thời lượng thực tế; không suy ra không có execution vĩnh viễn.

Kiểm thử local: 245 test Python đạt (0 lỗi, 0 bỏ qua); Terraform fmt/validate đạt và 5 mock plan đạt.
Trong đó có 36 test preflight, 17 test probe và 49 test smoke với dữ liệu/client/đồng hồ tự dựng;
ca Moto 1/20 tài liệu có replay và tên file bắt đầu bằng dấu chấm đều đạt.
Hai ZIP được build lại kèm dependency đã khóa; nguồn và hash đối chiếu với manifest.
Test/import ZIP chạy trên Python 3.13.14; runtime Lambda Python 3.12 chưa được kiểm thử.
Validation và việc còn chờ: xem docs/tv2/IMPLEMENTATION_STATUS.md.
AWS deployment, IAM thật, notification/retry/DLQ/alarm thật, TV1/TV4 integration chưa được xác nhận.
Fixture và số tiền trong ví dụ schema được ghi rõ là dữ liệu mẫu; p95/chi phí/độ chính xác OCR chưa đo.
Tên/ARN thật và các phần TV1/TV3/TV4/TV5 còn thiếu giữ chờ xác nhận.
Không đánh dấu PROGRESS hoàn tất trước khi test + merge theo quy tắc repo.
