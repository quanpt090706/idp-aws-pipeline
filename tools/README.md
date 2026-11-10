# Công cụ phát triển local

Thư mục này chứa công cụ hỗ trợ lập trình và kiểm thử, không được đóng gói vào
Lambda production.

## `local_ocr/`

API OCR chạy trên máy để TV3 và TV1 thử hóa đơn thật khi chưa có quyền Amazon
Textract. Công cụ gọi Poppler/Tesseract bên ngoài Python rồi trả cùng output
contract với parser TV3.

Chạy từ thư mục gốc:

```bash
python3 -m tools.local_ocr.server
```

Hướng dẫn đầy đủ: [`docs/tv3/OCR_LOCAL_TAM_THOI.md`](../docs/tv3/OCR_LOCAL_TAM_THOI.md).
