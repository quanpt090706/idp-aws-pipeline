# THEO DÕI TIẾN ĐỘ ĐỒ ÁN

> Cập nhật lần đầu: 06/11/2026
> Tài liệu chi tiết: [`output.md`](output.md) và [`task-breakdown.md`](task-breakdown.md)

File này là bảng tiến độ chung của nhóm. Mỗi Pull Request hoàn thành một công việc phải cập nhật checklist tương ứng.

---

## 1. Quy tắc cập nhật

- `[ ]`: chưa hoàn thành.
- `[x]`: đã hoàn thành, đã test và đã merge vào `main`.
- Mỗi thành viên chịu trách nhiệm cập nhật task của mình trong cùng PR.

---

## 2. Thông tin thành viên

| Mã | Họ tên/GitHub | Vai trò             | Trạng thái hiện tại |
| --- | --------------- | -------------------- | ----------------------- |
| TV1 | Chưa điền    | Frontend & Auth      | Chưa bắt đầu        |
| TV2 | Chưa điền    | Ingestion & Queue    | Chưa bắt đầu        |
| TV3 | Chưa điền    | Core OCR / AI        | Chưa bắt đầu        |
| TV4 | Chưa điền    | Data & Orchestration | Chưa bắt đầu        |
| TV5 | Chưa điền    | DevOps & Infra       | Chưa bắt đầu        |

---

## 3. Tổng quan các mốc

- [ ] **M0 — Thống nhất:** Nhóm đã duyệt thứ tự triển khai và phân công.
- [ ] **M1 — Nền móng:** Hạ tầng tối thiểu, giao diện giả, parser khung và thiết kế dữ liệu đã sẵn sàng.
- [ ] **M2 — Tiếp nhận file:** Upload → S3 → Validate → SQS hoạt động.
- [ ] **M3 — Xử lý tài liệu:** Step Functions → Textract → Parser → DynamoDB hoạt động.
- [ ] **M4 — Sản phẩm hoàn chỉnh:** Website upload và xem được kết quả của cả hai loại tài liệu.
- [ ] **M5 — Sẵn sàng demo:** Kiểm thử lỗi, bảo mật, log, chi phí, báo cáo và tổng duyệt hoàn tất.

---

## 4. Giai đoạn 0 — Cả nhóm thống nhất

Phụ trách: Nhóm trưởng điều phối, cả nhóm duyệt.

- [X] Thống nhất thứ tự các giai đoạn.
- [X] Thống nhất vai trò của TV1–TV5 theo `README.md`.
- [ ] Chốt phạm vi bắt buộc của bản demo.
- [ ] Chốt loại file, kích thước và số trang tối đa.
- [ ] Chốt cấu trúc dữ liệu chung.
- [ ] Chốt cấu trúc kết quả hóa đơn.
- [ ] Chốt cấu trúc kết quả bảng điểm.
- [ ] Chốt trạng thái: `UPLOAD_PENDING`, `QUEUED`, `PROCESSING`, `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`, `REJECTED`.
- [ ] Chốt API giữa website và backend.
- [ ] Chốt message mà TV2 bàn giao cho TV4.
- [ ] Chuẩn bị bộ test đã ẩn danh: tối thiểu 10 hóa đơn + 10 bảng điểm.

Hoàn thành giai đoạn khi: TV1 có thể làm giao diện giả, TV2 có thể tạo message, TV3 có thể viết parser và TV4 có thể thiết kế database từ cùng một contract.

---

## 5. Giai đoạn 1 — Dựng khung song song

### TV5 — Tạo nền móng AWS

- [ ] Chốt AWS region, tên project, tên môi trường và tags.
- [ ] Tạo Terraform skeleton, variables và outputs.
- [ ] Tạo S3 Upload bucket.
- [ ] Tạo S3 Results bucket.
- [ ] Tạo DynamoDB Documents.
- [ ] Tạo DynamoDB JobCallbacks và TTL.
- [ ] Tạo SQS Processing Queue và DLQ.
- [ ] Tạo SNS Textract Completion Topic.
- [ ] Tạo Lambda skeleton cho các module.
- [ ] Tạo Step Functions skeleton.
- [ ] Tạo CloudWatch log groups.
- [ ] Kiểm tra `terraform fmt`, `validate`, `plan`.
- [ ] Deploy thành công môi trường `dev` tối thiểu.

### TV1 — Làm giao diện bằng dữ liệu giả

- [ ] Vẽ luồng login → upload → processing → result.
- [ ] Tạo frontend skeleton và lệnh build.
- [ ] Làm trang đăng nhập giả.
- [ ] Làm trang upload hóa đơn/bảng điểm.
- [ ] Làm trạng thái loading, empty và error.
- [ ] Làm trang kết quả hóa đơn bằng mock JSON.
- [ ] Làm trang kết quả bảng điểm bằng mock JSON.
- [ ] Frontend build thành công.

### TV2 — Viết phần kiểm tra file

- [ ] Viết quy tắc chấp nhận/từ chối file.
- [ ] Tạo S3 event mẫu.
- [ ] Viết hàm đọc và URL-decode S3 key.
- [ ] Viết hàm kiểm tra loại file.
- [ ] Viết hàm kiểm tra kích thước.
- [ ] Viết hàm tạo SQS message theo contract.
- [ ] Viết unit test cho file hợp lệ và không hợp lệ.

### TV3 — Viết parser bằng dữ liệu mẫu

- [ ] Chuẩn bị raw Textract JSON mẫu cho hóa đơn.
- [ ] Chuẩn bị raw Textract JSON mẫu cho bảng điểm.
- [ ] Viết parser hóa đơn khung.
- [ ] Trích xuất vendor, date và total.
- [ ] Trích xuất danh sách sản phẩm.
- [ ] Viết parser bảng điểm khung.
- [ ] Trích xuất thông tin sinh viên.
- [ ] Trích xuất danh sách môn học.
- [ ] Viết unit test cho trường hợp thiếu dữ liệu.

### TV4 — Thiết kế dữ liệu và quy trình

- [ ] Liệt kê các cách hệ thống cần đọc/ghi dữ liệu.
- [ ] Chốt DynamoDB key và GSI.
- [ ] Chốt JobCallbacks schema và TTL.
- [ ] Chốt quy tắc chuyển trạng thái.
- [ ] Vẽ quy trình Step Functions.
- [ ] Thiết kế happy path.
- [ ] Thiết kế retry, timeout và failure path.
- [ ] Tạo state machine bằng các Lambda giả.

Hoàn thành giai đoạn khi: hạ tầng `dev` tối thiểu đã có; frontend hiển thị được mock data; validation, parser và state machine skeleton có test cơ bản.

---

## 6. Giai đoạn 2 — TV2 kết nối luồng tiếp nhận file

Phụ trách chính: TV2. Hỗ trợ hạ tầng: TV5. Nhận bàn giao: TV4.

- [ ] Kết nối S3 ObjectCreated với Lambda Validate.
- [ ] Lambda Validate đọc được metadata của file.
- [ ] File hợp lệ được cập nhật `QUEUED`.
- [ ] File không hợp lệ được cập nhật `REJECTED` và có lý do.
- [ ] File hợp lệ được gửi vào SQS.
- [ ] Cấu hình SQS visibility timeout và retry.
- [ ] Cấu hình DLQ và redrive policy.
- [ ] Viết Lambda Workflow Starter nhận message từ SQS.
- [ ] Workflow Starter gọi được Step Functions.
- [ ] Hai event trùng nhau không tạo hai quy trình xử lý.
- [ ] Test file PDF/JPG/PNG hợp lệ.
- [ ] Test file sai loại, quá lớn và event bị lặp.

Bàn giao cho TV4:

- [ ] Có sample SQS message thật.
- [ ] Có input mà Step Functions nhận được.
- [ ] Có PR, cách test và bằng chứng log.

Hoàn thành giai đoạn khi:

```text
Upload file → S3 → Validate → SQS → Workflow Starter
```

---

## 7. Giai đoạn 3 — TV4 tạo luồng điều phối

Phụ trách chính: TV4. Hỗ trợ: TV3 và TV5.

- [ ] Hiện thực Step Functions từ sơ đồ đã duyệt.
- [ ] Nhận đúng input từ Workflow Starter.
- [ ] Ghi trạng thái `PROCESSING`.
- [ ] Phân nhánh đúng `INVOICE` và `TRANSCRIPT`.
- [ ] Dùng callback token để chờ Textract.
- [ ] Cấu hình retry cho lỗi tạm thời.
- [ ] Cấu hình timeout cho bước chờ.
- [ ] Cấu hình Catch và ghi `FAILED`.
- [ ] Tạo persistence adapter cập nhật DynamoDB.
- [ ] Kiểm tra state machine bằng Lambda/kết quả giả.

Hoàn thành giai đoạn khi:

```text
SQS message → Step Functions → PROCESSING
→ kết quả giả → SUCCEEDED/FAILED
```

---

## 8. Giai đoạn 4 — TV3 kết nối Textract và parser

Phụ trách chính: TV3. Hỗ trợ callback/data: TV4. Hỗ trợ quyền: TV5.

- [ ] Chạy thử `StartExpenseAnalysis` với một hóa đơn.
- [ ] Chạy thử `StartDocumentAnalysis` với một bảng điểm.
- [ ] Viết Lambda Start Textract Job.
- [ ] Lưu `job_id`, `document_id`, callback token và TTL.
- [ ] Textract gửi thông báo hoàn thành qua SNS.
- [ ] Viết Lambda nhận SNS callback.
- [ ] Lấy đủ các trang kết quả Textract.
- [ ] Lưu raw JSON vào S3 Results.
- [ ] Không truyền raw JSON lớn qua Step Functions/DynamoDB.
- [ ] Hoàn thiện parser hóa đơn.
- [ ] Hoàn thiện parser bảng điểm.
- [ ] Tính confidence và warnings.
- [ ] Gắn `NEEDS_REVIEW` khi thiếu trường hoặc confidence thấp.
- [ ] Callback thành công làm Step Functions tiếp tục.
- [ ] Callback thất bại làm Step Functions đi vào nhánh lỗi.

Bàn giao cho TV4:

- [ ] Raw-result S3 key.
- [ ] Normalized JSON đúng data contract.
- [ ] Warnings, confidence và trạng thái đề xuất.
- [ ] Unit-test report và accuracy report ban đầu.

---

## 9. Giai đoạn 5 — TV4 lưu kết quả thật

Phụ trách chính: TV4. Bàn giao kết quả cho TV1.

- [ ] Tích hợp Lambda/parser thật của TV3 vào Step Functions.
- [ ] Lưu raw-result pointer.
- [ ] Lưu normalized invoice result.
- [ ] Lưu normalized transcript result.
- [ ] Cập nhật `SUCCEEDED` khi kết quả đạt yêu cầu.
- [ ] Cập nhật `NEEDS_REVIEW` khi thiếu/không chắc chắn.
- [ ] Cập nhật `FAILED` khi có lỗi kỹ thuật.
- [ ] Ngăn trạng thái cuối bị ghi đè sai.
- [ ] Test callback bị gửi hai lần.
- [ ] Test parser lỗi và database update lỗi.

Bàn giao cho TV1:

- [ ] Có document API response thật cho invoice.
- [ ] Có document API response thật cho transcript.
- [ ] Có response cho `NEEDS_REVIEW`, `FAILED` và `REJECTED`.

---

## 10. Giai đoạn 6 — TV1 kết nối website thật

Phụ trách chính: TV1. Hỗ trợ hạ tầng: TV5. Hỗ trợ dữ liệu: TV4.

- [ ] Tích hợp Cognito login/logout.
- [ ] API từ chối request không có token hợp lệ.
- [ ] Viết API tạo document và presigned upload URL.
- [ ] Website upload trực tiếp lên S3.
- [ ] Viết API danh sách document có pagination.
- [ ] Viết API xem chi tiết document.
- [ ] User chỉ xem được document của mình.
- [ ] Website hiển thị danh sách và trạng thái.
- [ ] Polling dừng khi document có trạng thái cuối.
- [ ] Hiển thị invoice result thật.
- [ ] Hiển thị transcript result thật.
- [ ] Hiển thị warnings và confidence.
- [ ] Hiển thị thông báo lỗi dễ hiểu.
- [ ] Deploy frontend qua CloudFront.
- [ ] Frontend bucket không public.
- [ ] CORS chỉ cho phép origin cần thiết.

Hoàn thành giai đoạn khi:

```text
Đăng nhập → Upload → Processing → Xem kết quả
```

hoạt động cho cả hóa đơn và bảng điểm.

---

## 11. Giai đoạn 7 — TV5 hoàn thiện vận hành

Phụ trách chính: TV5. Các thành viên cung cấp test/log cho module của mình.

- [ ] Tách IAM role theo từng Lambda/dịch vụ.
- [ ] Không sử dụng quyền rộng không cần thiết.
- [ ] S3 Upload, Results và Frontend đúng chính sách public/private.
- [ ] Bật mã hóa lưu trữ.
- [ ] Cấu hình log retention.
- [ ] Log có `document_id` và `request_id`.
- [ ] Log không chứa token, presigned URL, task token hoặc PII.
- [ ] Tạo CloudWatch Dashboard.
- [ ] Tạo alarm cho Lambda errors.
- [ ] Tạo alarm cho SQS message chờ quá lâu.
- [ ] Tạo alarm khi DLQ có message.
- [ ] Tạo alarm khi Step Functions thất bại/timeout.
- [ ] Cấu hình X-Ray nếu thuộc phạm vi đã chốt.
- [ ] Tạo CI chạy lint, unit test, build và Terraform checks.
- [ ] Cấu hình deploy bằng GitHub OIDC, không dùng AWS key dài hạn.
- [ ] Tạo AWS Budget và cảnh báo chi phí.
- [ ] Tạo S3 lifecycle cho dữ liệu demo.
- [ ] Viết hướng dẫn deploy, rollback và destroy.

---

## 12. Giai đoạn 8 — Cả nhóm kiểm thử và demo

### Luồng chính

- [ ] Hóa đơn rõ → `SUCCEEDED` và hiển thị đúng.
- [ ] Hóa đơn mờ/thiếu field → `NEEDS_REVIEW`.
- [ ] Bảng điểm một trang → hiển thị đúng sinh viên và môn.
- [ ] Bảng điểm nhiều trang → không mất trang/header lặp.

### Luồng lỗi

- [ ] File sai định dạng → `REJECTED`, không gọi Textract.
- [ ] File vượt giới hạn → bị chặn và có lý do.
- [ ] S3/SQS event gửi lặp → không OCR hai lần.
- [ ] Textract lỗi → retry/Catch → `FAILED`.
- [ ] Message lỗi nhiều lần → DLQ.
- [ ] Callback timeout → state machine kết thúc có kiểm soát và alarm.

### Bảo mật

- [ ] User B không xem được document User A.
- [ ] API không token bị từ chối.
- [ ] Presigned URL hết hạn không còn sử dụng được.
- [ ] Không bucket nhạy cảm nào public.
- [ ] Repo không chứa secret, tfstate, tfvars thật hoặc PII.

### Hiệu năng và đo lường

- [ ] Test 10–20 file được upload gần đồng thời.
- [ ] Ghi tỷ lệ `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`.
- [ ] Ghi thời gian xử lý trung bình và p95.
- [ ] Ghi accuracy cho các field bắt buộc.
- [ ] Ghi chi phí ước tính/thực tế của bộ test.

### Tài liệu và demo

- [ ] README phản ánh đúng hệ thống thực tế.
- [ ] Sơ đồ kiến trúc khớp với code/Terraform.
- [ ] Có hướng dẫn deploy, test và cleanup.
- [ ] Hoàn thành báo cáo.
- [ ] Hoàn thành slide.
- [ ] Chốt kịch bản demo 8–10 phút.
- [ ] Tổng duyệt demo lần 1.
- [ ] Sửa các lỗi sau lần 1.
- [ ] Tổng duyệt demo lần 2.
- [ ] Quay video demo dự phòng.
- [ ] Chụp bằng chứng S3, SQS, Step Functions, DynamoDB và CloudWatch.
- [ ] Tạo release tag cho bản demo.

---

## 13. Tiến độ theo tuần

### Tuần 1 — Contract và khung ban đầu

- [ ] Giai đoạn 0 hoàn thành.
- [ ] TV5 deploy hạ tầng `dev` tối thiểu.
- [ ] TV1 hiển thị được mock invoice/transcript.
- [ ] TV2 hoàn thành validation skeleton và unit test.
- [ ] TV3 có hai parser skeleton và raw fixtures.
- [ ] TV4 có database/state-machine design và stub flow.

### Tuần 2 — Module chính

- [ ] TV1 đăng nhập và upload được.
- [ ] TV2 hoàn thành S3 → Validate → SQS → Workflow Starter.
- [ ] TV3 hoàn thành Textract callback và hai parser.
- [ ] TV4 hoàn thành state machine, persistence và status.
- [ ] TV5 hoàn thành hạ tầng/IAM cần cho tích hợp.

### Tuần 3 — Tích hợp

- [ ] Invoice chạy end-to-end trên website.
- [ ] Transcript chạy end-to-end trên website.
- [ ] Retry, DLQ, duplicate event và failure path được test.
- [ ] Authorization và ownership được test.
- [ ] Dashboard, alarms và CI hoạt động.

### Tuần 4 — Ổn định và demo

- [ ] Chạy toàn bộ test matrix.
- [ ] Đo accuracy, latency, success rate và chi phí.
- [ ] Fix toàn bộ lỗi blocker/high.
- [ ] Hoàn thành README, báo cáo và slide.
- [ ] Tổng duyệt hai lần và quay video dự phòng.
- [ ] Tạo release tag.

---

## 14. Blocker hiện tại

| Ngày | Thành viên | Task/Giai đoạn | Vấn đề               | Cần ai hỗ trợ | Trạng thái |
| ----- | ------------ | ---------------- | ----------------------- | ---------------- | ------------ |
| —    | —           | —               | Chưa ghi nhận blocker | —               | —           |

---

## 15. Quyết định/thay đổi cần cả nhóm duyệt

| Ngày      | Đề xuất                                                       | Lý do                         | Ảnh hưởng  | Kết quả   |
| ---------- | ---------------------------------------------------------------- | ------------------------------ | ------------- | ----------- |
| 06/11/2026 | Duyệt thứ tự 8 giai đoạn và phân công theo `README.md` | Thống nhất cách triển khai | Toàn dự án | Đã duyệt |

---

## 16. Xác nhận hoàn thành dự án

- [ ] M0 đến M5 đều hoàn thành.
- [ ] Tất cả task P0 đã merge và test.
- [ ] Không còn blocker hoặc lỗi mức nghiêm trọng.
- [ ] Cả 5 thành viên đã xác nhận phần bàn giao của mình.
- [ ] Nhóm trưởng đã duyệt release dùng để demo.
