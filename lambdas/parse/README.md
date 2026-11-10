# TV3 - Textract và parser

TV3 có hai phần tách biệt:

- `parsers/`: chuyển raw Textract JSON thành normalized JSON. Phần này không
  gọi AWS nên có thể chạy hoàn toàn local.
- `../start-job/handler.py` và `handler.py`: khởi động Textract async, nhận
  SNS callback, lấy đủ các trang, lưu raw JSON và tiếp tục Step Functions.

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

Ngưỡng confidence mặc định là `80.0`. Lambda Parse trả
`NEEDS_REVIEW` khi có warning hoặc confidence thấp hơn ngưỡng; nhóm có thể
điều chỉnh giá trị này trước khi chạy bộ dữ liệu demo.

## Kiểm tra phần tích hợp Giai đoạn 4

Sau khi cài `requirements-dev.txt`:

```bash
python3 -m pytest -q tests/tv3 tests/test_invoice_parser.py tests/test_transcript_parser.py
```

Test sử dụng AWS client giả nên không cần credentials, không gọi mạng và không
phát sinh chi phí AWS.

## Cấu hình AWS cần được TV5 cung cấp

Lambda `StartJob`:

- `SNS_TOPIC_ARN`
- `TEXTRACT_ROLE_ARN`
- `JOB_CALLBACKS_TABLE`

Lambda `Parse`:

- `JOB_CALLBACKS_TABLE`
- `S3_RESULTS_BUCKET`
- `CONFIDENCE_THRESHOLD` (không bắt buộc, mặc định `80.0`)

Contract input/callback chuẩn nằm trong `docs/tv4/CONTRACT.md`. Việc test trên AWS
thật chỉ thực hiện sau khi quyền IAM, SNS subscription và các biến môi
trường trên đã được deploy.
