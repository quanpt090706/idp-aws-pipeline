# TV3 — Core OCR / AI

Đây là thư mục tài liệu do TV3 sở hữu. TV3 phụ trách khởi động Amazon
Textract, nhận callback, lấy toàn bộ kết quả OCR và chuẩn hóa hóa đơn/bảng điểm
thành JSON dùng chung cho TV4 và TV1.

## Đọc từ đâu

1. [OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md): cấu trúc JSON mà parser TV3 trả về.
2. [OCR_LOCAL_TAM_THOI.md](OCR_LOCAL_TAM_THOI.md): phương án OCR local tạm
   thời khi AWS Academy chưa cấp Textract.
3. [Lambda Parse README](../../lambdas/parse/README.md): lệnh test parser local,
   biến môi trường và smoke test AWS Giai đoạn 4.
4. [Luồng Textract bất đồng bộ](../flows/textract-async-flow.md): sơ đồ
   StartJob → Textract → SNS → Parse.
5. [Hợp đồng TV3–TV4](../tv4/CONTRACT.md): input StartJob, callback payload và
   bảng JobCallbacks.

## Mã nguồn TV3

| Phần | Vị trí |
|---|---|
| Khởi động Textract | `lambdas/start-job/handler.py` |
| Nhận SNS và lấy kết quả | `lambdas/parse/handler.py` |
| Parser hóa đơn | `lambdas/parse/parsers/invoice.py` |
| Parser bảng điểm | `lambdas/parse/parsers/transcript.py` |
| OCR local tạm thời | `tools/local_ocr/` |
| Test TV3 | `tests/tv3/`, `tests/test_invoice_parser.py`, `tests/test_transcript_parser.py` |
| Smoke test AWS thật | `scripts/tv3_stage4_smoke.py` |

## Phân biệt tài liệu TV3 và tài liệu dùng chung

- `docs/tv3/` là tài liệu TV3 chịu trách nhiệm cập nhật.
- `docs/flows/` mô tả luồng của nhiều thành viên nên vẫn nằm ở thư mục chung.
- `docs/tv4/CONTRACT.md` do TV4 quản lý nhưng là hợp đồng TV3 phải tuân theo.
- `PROGRESS.md` ở thư mục gốc là checklist chung của cả nhóm.

Phương án OCR local không thay thế kết quả nghiệm thu Textract. Các checklist
AWS thật trong Giai đoạn 4 chỉ được đánh dấu sau khi chạy thành công trên tài
khoản có quyền Amazon Textract.
