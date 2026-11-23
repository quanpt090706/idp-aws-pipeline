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

## Smoke test Giai đoạn 4 trên AWS dev

Sau khi TV5 deploy root `infra/` và xác nhận đúng account/region/role, lấy các
giá trị bằng `terraform output`. Chạy một hóa đơn trước:

```bash
python3 scripts/tv3_stage4_smoke.py \
  --file DUONG_DAN_DEN_FILE_HOA_DON.pdf \
  --document-type INVOICE \
  --upload-bucket TEN_UPLOAD_BUCKET \
  --results-bucket TEN_RESULTS_BUCKET \
  --documents-table TEN_DOCUMENTS_TABLE \
  --state-machine-arn ARN_STATE_MACHINE \
  --region us-east-1 \
  --confirm-dev-write
```

Lệnh này cố ý bỏ qua website và TV2 để kiểm tra riêng đoạn:

```text
S3 → Step Functions → StartJob → Textract → SNS → Parse
→ S3 Results → DynamoDB
```

Lệnh chỉ thành công khi execution kết thúc, trạng thái document là `SUCCEEDED`
hoặc `NEEDS_REVIEW`, và raw Textract JSON thật tồn tại trong Results bucket.
Không thêm `--confirm-dev-write` nếu chưa kiểm tra đúng tài khoản AWS dev vì
lệnh sẽ tạo document, upload object và gọi Textract có tính phí theo trang.
