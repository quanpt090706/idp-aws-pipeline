## Thứ tự tổng thể

```text
Bước 0: Cả nhóm thống nhất dữ liệu
                    ↓
Bước 1: TV5 tạo nền móng AWS
                    ↓
    ┌───────────────┼────────────────┐
    ↓               ↓                ↓
TV1 làm giao diện  TV2 kiểm tra file  TV3 viết xử lý tài liệu
    ↓               ↓                ↓
    └───────────────┼────────────────┘
                    ↓
        TV4 nối và điều phối các bước
                    ↓
        TV1 kết nối website thật
                    ↓
           Cả nhóm kiểm thử
```

Tuy nhiên, TV4 cũng có thể thiết kế cơ sở dữ liệu và sơ đồ xử lý ngay từ đầu, không cần ngồi chờ.

---

# Bước 0 – Cả nhóm làm cùng nhau

Thời gian dự kiến: ngày đầu tiên.

Cả 5 thành viên phải thống nhất:

- File nào được chấp nhận: PDF, JPG, PNG.
- Hai loại tài liệu: hóa đơn và bảng điểm.
- Kết quả hóa đơn gồm những trường nào.
- Kết quả bảng điểm gồm những trường nào.
- Các trạng thái xử lý.
- Cách đặt tên dữ liệu.

# Bước 1 – TV5 tạo nền móng AWS

TV5 là người cần bắt đầu phần AWS trước.

Thứ tự của TV5:

1. Chọn khu vực AWS.
2. Đặt quy tắc tên tài nguyên.
3. Tạo nơi chứa file.
4. Tạo hàng chờ.
5. Tạo cơ sở dữ liệu.
6. Tạo các chương trình Lambda trống.
7. Tạo quyền truy cập.
8. Tạo hệ thống ghi log.

TV5 cần tạo tối thiểu:

```text
S3 Upload
S3 Results
SQS
DynamoDB
SNS
Lambda trống
Step Functions trống
CloudWatch
```

Kết quả TV5 phải bàn giao:

```text
Có thể tải file thử lên S3
→ hệ thống nhận được thông báo
→ Lambda trống chạy
→ có log trong CloudWatch
```

TV5 chưa cần chờ code thật của TV1–TV4. Ban đầu có thể dùng Lambda chỉ in:

```text
Received document
```

Sau khi nền móng tối thiểu hoạt động, TV2–TV4 mới kết nối AWS thật thuận lợi.

---

# Trong lúc TV5 làm nền móng

## TV1 làm giao diện demo

TV1 làm theo thứ tự:

1. Vẽ giao diện.
2. Làm trang đăng nhập.
3. Làm trang upload.
4. Làm trang “đang xử lý”.
5. Làm trang kết quả hóa đơn.
6. Làm trang kết quả bảng điểm.
7. Dùng dữ liệu giả để kiểm tra.

Ví dụ TV1 có thể dùng:

```javascript
const mockInvoice = {
  vendor_name: "Coopmart",
  total_amount: 450000
};
```

## TV2 viết chương trình kiểm tra file

TV2 làm theo thứ tự:

1. Quy định file nào được chấp nhận.
2. Viết chương trình đọc thông báo file mới.
3. Kiểm tra định dạng.
4. Kiểm tra kích thước.
5. Tạo nội dung đưa vào hàng chờ.
6. Viết kiểm thử bằng dữ liệu giả.

TV2 chưa cần S3 thật để viết phần kiểm tra ban đầu. Có thể sử dụng một sự kiện giả:

```json
{
  "bucket": "test-bucket",
  "key": "uploads/invoice01.pdf"
}
```

## TV3 viết chương trình xử lý bằng dữ liệu mẫu

TV3 làm theo thứ tự:

1. Chuẩn bị mẫu hóa đơn và bảng điểm.
2. Chuẩn bị kết quả Textract mẫu.
3. Viết chương trình xử lý hóa đơn.
4. Viết chương trình xử lý bảng điểm.
5. Kiểm tra trường hợp thiếu dữ liệu.
6. Kiểm tra trường hợp chữ mờ hoặc độ tin cậy thấp.

TV3 chưa cần kết nối Textract thật ngay. Trước tiên chỉ cần làm được:

```text
Textract JSON mẫu
→ chương trình xử lý
→ JSON có cấu trúc
```

Cập nhật tiến độ TV3 ngày 09/11/2026:

1. Đã chuẩn bị raw Textract JSON mẫu cho hóa đơn và bảng điểm.
2. Đã viết parser hóa đơn và parser bảng điểm.
3. Đã chuẩn hóa ngày, số tiền, tiền tệ, confidence và warnings.
4. Đã xử lý trường hợp thiếu dữ liệu hoặc độ tin cậy thấp.
5. Đã có fixture, JSON Schema và 6 unit test parser chạy thành công.
6. Parser local đã được merge vào `main`.

Kết quả local TV3 đã đạt:

```text
Textract JSON mẫu
→ parser hóa đơn/bảng điểm
→ normalized JSON + confidence + warnings
```

## TV4 thiết kế nơi lưu và các bước xử lý

TV4 làm theo thứ tự:

1. Thiết kế bảng lưu tài liệu.
2. Quy định các trạng thái.
3. Vẽ thứ tự xử lý.
4. Quy định khi nào thành công.
5. Quy định khi nào cần kiểm tra lại.
6. Quy định khi nào thất bại.

TV4 cần xác định luồng:

```text
QUEUED
→ PROCESSING
→ SUCCEEDED
```

Hoặc:

```text
PROCESSING
→ NEEDS_REVIEW
```

Hoặc:

```text
PROCESSING
→ FAILED
```

---

# Bước 2 – TV2 kết nối phần tiếp nhận file

Khi TV5 đã tạo S3, SQS và Lambda, TV2 bắt đầu kết nối thật.

Thứ tự TV2 làm:

1. Kết nối S3 với Lambda Validate.
2. Upload một file thử.
3. Lambda nhận thông báo file mới.
4. Lambda kiểm tra file.
5. File hợp lệ được đưa vào SQS.
6. File không hợp lệ bị từ chối.
7. Kiểm tra file lỗi nhiều lần có vào DLQ không.
8. Kết nối SQS với chương trình bắt đầu xử lý.

Kết quả cần đạt:

```text
Upload file hợp lệ
→ S3
→ Lambda kiểm tra
→ SQS có message
```

TV2 bàn giao message cho TV4:

```json
{
  "document_id": "doc_001",
  "document_type": "INVOICE",
  "bucket": "upload-bucket",
  "key": "uploads/invoice01.pdf"
}
```

---

# Bước 3 – TV4 tạo phần quản lý quy trình

Sau khi TV2 tạo được message, TV4 làm phần điều phối thật.

Thứ tự TV4 làm:

1. Tạo bảng Documents trong DynamoDB.
2. Tạo nơi lưu thông tin chờ Textract.
3. Tạo Step Functions.
4. Nhận message từ phần TV2.
5. Ghi trạng thái `PROCESSING`.
6. Gọi chương trình của TV3.
7. Chờ TV3 trả kết quả.
8. Lưu dữ liệu.
9. Ghi trạng thái cuối.

Ban đầu TV4 có thể dùng chương trình giả thay cho TV3:

```text
TV4 gọi chương trình giả
→ chờ 2 giây
→ nhận kết quả giả
→ lưu DynamoDB
```

Kết quả cần đạt:

```text
SQS
→ bắt đầu quy trình
→ PROCESSING
→ dữ liệu giả
→ SUCCEEDED
```

---

# Bước 4 – TV3 kết nối Textract thật

Khi TV5 đã tạo quyền AWS và TV4 có luồng cơ bản, TV3 kết nối Textract.

Thứ tự TV3 làm:

1. Nhận đường dẫn file từ TV4.
2. Kiểm tra loại tài liệu.
3. Nếu là hóa đơn, gọi chức năng đọc hóa đơn.
4. Nếu là bảng điểm, gọi chức năng đọc bảng và biểu mẫu.
5. Nhận mã công việc từ Textract.
6. Chờ thông báo Textract hoàn thành.
7. Lấy đầy đủ kết quả.
8. Lưu kết quả gốc vào S3 Results.
9. Chạy parser phù hợp.
10. Gửi dữ liệu đã xử lý lại cho TV4.

Luồng hóa đơn:

```text
invoice.pdf
→ Textract đọc hóa đơn
→ parser hóa đơn
→ vendor, date, total, items
```

Luồng bảng điểm:

```text
transcript.pdf
→ Textract đọc bảng
→ parser bảng điểm
→ student, subjects, scores
```

Kết quả TV3 bàn giao cho TV4:

```json
{
  "document_type": "INVOICE",
  "confidence": 92.5,
  "warnings": [],
  "extracted": {
    "vendor_name": "Coopmart",
    "total_amount": 450000
  }
}
```

Cập nhật hiện thực local của TV3 ngày 09/11/2026:

1. Đã viết Lambda Start Job gọi đúng chức năng Textract cho hóa đơn
   và bảng điểm.
2. Đã tạo mã chống khởi động trùng và lưu `job_id`, `document_id`,
   callback token, loại tài liệu và TTL vào JobCallbacks.
3. Đã viết Lambda nhận SNS callback, lấy đủ các trang kết quả và
   bỏ qua callback đã xử lý.
4. Đã viết phần lưu raw JSON vào S3 Results và không gửi raw JSON lớn
   qua Step Functions.
5. Đã nối callback với parser, `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED` và
   hai nhánh Step Functions thành công/thất bại.
6. Đã có 16 unit test handler; toàn bộ test Python trong repo đạt
   300 test và 5 subtest.

Phần còn chờ AWS `dev`:

```text
TV5 cấu hình IAM + biến môi trường + SNS subscription
→ merge code TV3
→ deploy môi trường dev chung
→ chạy thử hóa đơn và bảng điểm thật
```

Tài liệu bàn giao của TV3:

```text
lambdas/parse/README.md
PROGRESS.md — Giai đoạn 4
docs/tv4/CONTRACT.md
tests/tv3/
```

---

# Bước 5 – TV4 lưu kết quả thật

Khi TV3 đã trả dữ liệu th	ật, TV4 thay dữ liệu giả bằng dữ liệu thật.

Thứ tự:

1. Nhận kết quả từ TV3.
2. Kiểm tra kết quả có hợp lệ không.
3. Nếu tốt, ghi `SUCCEEDED`.
4. Nếu thiếu dữ liệu, ghi `NEEDS_REVIEW`.
5. Nếu chương trình lỗi, ghi `FAILED`.
6. Lưu dữ liệu vào DynamoDB.
7. Lưu đường dẫn kết quả gốc.
8. Kết thúc quá trình.

Kết quả cần đạt:

```text
Upload file
→ xử lý Textract
→ parser
→ DynamoDB có kết quả thật
```

---

# Bước 6 – TV1 kết nối website với hệ thống thật

Khi TV4 đã lưu được kết quả, TV1 thay dữ liệu giả bằng API thật.

Thứ tự TV1 làm:

1. Kết nối đăng nhập Cognito.
2. Gọi API để lấy đường dẫn upload.
3. Upload file lên S3.
4. Gọi API để xem trạng thái.
5. Hiển thị “đang xử lý”.
6. Tiếp tục kiểm tra cho đến khi hoàn thành.
7. Lấy kết quả từ DynamoDB thông qua API.
8. Hiển thị hóa đơn hoặc bảng điểm.
9. Kiểm tra người dùng không xem được tài liệu người khác.

Kết quả cuối cùng:

```text
Website
→ đăng nhập
→ upload
→ chờ
→ xem kết quả
```

---

# Bước 7 – TV5 hoàn thiện vận hành

Sau khi hệ thống đã nối được, TV5 tiếp tục:

1. Kiểm tra quyền của từng Lambda.
2. Tạo hệ thống tự động kiểm tra code.
3. Tạo log và bảng theo dõi.
4. Tạo cảnh báo khi Lambda lỗi.
5. Tạo cảnh báo khi hàng chờ bị nghẽn.
6. Tạo cảnh báo chi phí.
7. Kiểm tra các S3 không bị công khai.
8. Viết hướng dẫn triển khai và xóa tài nguyên.

Kết quả cần đạt:

```text
Có lỗi
→ CloudWatch ghi nhận
→ nhóm nhận cảnh báo
```

TV5 phải đảm bảo không cần tạo dịch vụ AWS bằng tay lại từ đầu khi triển khai môi trường mới.

---

# Bước 8 – Cả nhóm kiểm thử

Thứ tự kiểm thử:

1. Hóa đơn rõ.
2. Hóa đơn mờ.
3. Bảng điểm một trang.
4. Bảng điểm nhiều trang.
5. File sai định dạng.
6. File quá lớn.
7. Một file bị gửi hai lần.
8. Textract xảy ra lỗi.
9. Người dùng khác cố xem tài liệu.
10. Nhiều file được upload gần nhau.

Khi có lỗi, người phụ trách phần nào sửa phần đó:

| Lỗi                                    | Người sửa chính |
| --------------------------------------- | ------------------- |
| Không đăng nhập/upload được      | TV1                 |
| File không vào hàng chờ             | TV2                 |
| Textract hoặc parser sai               | TV3                 |
| Sai trạng thái/không lưu kết quả  | TV4                 |
| Sai quyền, deploy hoặc không có log | TV5                 |

## Thứ tự ngắn gọn nhất

```text
1. Cả nhóm chốt dữ liệu và cách kết nối
2. TV5 tạo nền móng AWS
3. TV1 làm giao diện bằng dữ liệu giả
4. TV2 làm kiểm tra file và hàng chờ
5. TV3 làm parser bằng dữ liệu mẫu
6. TV4 làm cơ sở dữ liệu và quy trình giả
7. TV2 nối S3 → kiểm tra → SQS
8. TV3 nối Textract → parser
9. TV4 nối toàn bộ và lưu kết quả
10. TV1 nối website với hệ thống thật
11. TV5 hoàn thiện quyền, log, cảnh báo và triển khai
12. Cả nhóm kiểm thử, sửa lỗi và tập demo
```

TV5 là người cần cung cấp nền móng sớm nhất. TV4 là người kết nối quy trình ở giữa. TV1 là người kết nối cuối cùng để tạo ra sản phẩm mà người dùng có thể sử dụng.
