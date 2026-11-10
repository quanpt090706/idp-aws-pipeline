# TV3 — Output contract của parser

Cả parser Textract và OCR local tạm thời phải trả cùng một khung kết quả để
TV4 lưu dữ liệu và TV1 hiển thị mà không phụ thuộc công cụ OCR phía sau.

## Khung chung

```json
{
  "document_type": "INVOICE",
  "confidence": 95.0,
  "warnings": [],
  "extracted": {}
}
```

- `document_type`: `INVOICE` hoặc `TRANSCRIPT`.
- `confidence`: số từ `0` đến `100`.
- `warnings`: danh sách cảnh báo có ít nhất `code`, `field`, `message`.
- `extracted`: dữ liệu đã chuẩn hóa theo từng loại tài liệu.
- Không tìm thấy trường thì trả `null`; parser không tự bịa giá trị.

## Hóa đơn

`extracted` gồm:

- `vendor_name`, `invoice_number`, `invoice_date`, `currency`.
- `subtotal`, `tax_amount`, `total_amount`.
- `items[]`: `description`, `quantity`, `unit_price`, `amount`, `confidence`.

Schema chính thức: [invoice-result.schema.json](../../lambdas/parse/schemas/invoice-result.schema.json).
Ví dụ đã chuẩn hóa: [invoice.json](../../tests/fixtures/expected/invoice.json).

## Bảng điểm

`extracted` gồm:

- `student_id`, `student_name`, `school_name`, `academic_year`, `gpa`.
- `subjects[]`: mã môn, tên môn, tín chỉ, điểm số và điểm chữ theo schema.

Schema chính thức: [transcript-result.schema.json](../../lambdas/parse/schemas/transcript-result.schema.json).
Ví dụ đã chuẩn hóa: [transcript.json](../../tests/fixtures/expected/transcript.json).

## Trạng thái sau khi tích hợp

- `SUCCEEDED`: đủ dữ liệu và đạt ngưỡng tin cậy.
- `NEEDS_REVIEW`: thiếu trường, có warning hoặc confidence thấp.
- `FAILED`: OCR/parser gặp lỗi kỹ thuật.

Raw JSON lớn được lưu ở S3 Results. Step Functions và DynamoDB chỉ nhận con
trỏ `s3_result_key` cùng normalized JSON cần thiết, không truyền toàn bộ raw
Textract response.
