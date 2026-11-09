# TV3 - Local Textract parsers

Giai đoạn này chỉ xử lý `raw Textract JSON -> normalized JSON`. Parser không import
`boto3`, không cần AWS credentials và không gọi mạng. Phần Start Job/SNS callback sẽ
được nối sau khi TV4/TV5 bàn giao contract và hạ tầng.

## Chạy local

Từ thư mục gốc của repository:

```bash
python3 -m unittest discover -s tests -v
```

Xem JSON đã chuẩn hóa:

```bash
python3 -m lambdas.parse.local_run invoice tests/fixtures/textract/invoice.json
python3 -m lambdas.parse.local_run transcript tests/fixtures/textract/transcript.json
```

## Output contract tạm thời

Parser trả object gồm `document_type`, `confidence`, `warnings` và `extracted` theo
data contract trong `docs/personal/output.md`. Trường không tìm thấy là `null`; parser
không bịa giá trị. Warning là object có tối thiểu `code`, `field`, `message`.

Ngưỡng confidence tạm thời là `80.0`. Đây là giá trị local để test
trường hợp chữ mờ; policy `NEEDS_REVIEW` chỉ được chốt ở task `PAR-003`.
