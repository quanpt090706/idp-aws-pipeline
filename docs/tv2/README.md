# TV2 — chạy local, nối Academy và bàn giao

Mã thật nằm trong `lambdas/validate` và `lambdas/workflow-starter`.
Contract triển khai theo đề xuất đã được chủ nhiệm phần TV2 đồng ý trong phiên làm việc này;
TV1/TV4 vẫn cần xác nhận giao diện liên thông trước khi ghép cả hệ thống.
Theo dõi từng Bước 0–13 tại [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).
TV5 nhận code và bắt đầu kiểm tra môi trường tại [TV5_START_HERE.md](TV5_START_HERE.md).

## 1. Kiểm thử trên máy

Mở PowerShell tại gốc repo (máy TV2 hiện dùng `D:\aws_ck\idp-aws-pipeline`;
máy TV5 dùng thư mục clone thực tế):

Nếu vừa clone và chưa có `.venv`, tạo bằng Python đã cài (ưu tiên 3.12 trùng Lambda):

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --junitxml=build/tv2/test-results.xml
.\.venv\Scripts\python.exe -m pip check
```

Test có gọi SDK được bọc Moto, dùng credential giả trong tiến trình test.
Ca integration chạy qua S3/DynamoDB/SQS/Step Functions giả lập, bao gồm 20 tài liệu và event lặp.
Moto không chứng minh IAM, S3 notification, SQS polling/retry, alarm hay Textract hoạt động trên AWS.

## 2. Đóng gói Lambda

```powershell
.\.venv\Scripts\python.exe scripts\build_tv2.py
```

Tạo `build/tv2/validate.zip`, `workflow-starter.zip` và manifest SHA256.
SDK và các dependency runtime được khóa phiên bản; pip chọn wheel cho Linux x86_64/Python 3.12.
Hai ZIP độc lập, handler/source nằm ở gốc ZIP. Không đóng gói test hay credential.
`--source-only` chỉ dành cho thử nghiệm dùng SDK sẵn trong runtime; bản triển khai dùng lệnh mặc định.
`build/` và `.venv/` được Git bỏ qua.

## 3. Thông tin Academy còn cần

Ngày 07/11/2026 đã xác minh một Cloud Foundations Sandbox tại `us-east-1`,
profile tạm `academy-lab` và Lambda role `LabRole`. Account ID/ARN của phiên lab cũ
không dùng làm cấu hình cho TV5; lấy lại thông tin thật bằng `tv2_identity.py`.

Kết quả phiên kiểm tra trước ngày 07/11/2026 (không phải kiểm tra lại AWS trong lượt sửa local này):

- `LabRole` trust Lambda nhưng không trust `states.amazonaws.com`; chưa có role Step Functions đã xác minh dùng được.
- Terraform plan đạt 30 add, 0 change, 0 destroy với consumer SQS tắt.
- Apply bị lab chặn `dynamodb:CreateTable` và explicit deny
  `s3:GetBucketObjectLockConfiguration` mà AWS provider cần khi quản lý bucket.
- Chỉ một bucket rỗng kịp được tạo; bucket đã bị xóa bằng destroy-plan riêng và state hiện trống.

Cloud Foundations Sandbox này vì vậy chưa đủ quyền dựng pipeline. Cần một Learner Lab/quyền khác,
hoặc TV5 cung cấp sẵn bucket + bảng Documents và TV4 cung cấp Standard state machine cùng role phù hợp.
Với lab mới, cần lấy:

1. Region được phép, Account ID 12 số, profile local (đề xuất `academy-lab`).
2. Role ARN dùng cho Lambda, trust principal `lambda.amazonaws.com` và quyền TV2.
3. Role ARN dùng cho Step Functions, trust principal `states.amazonaws.com`;
   hoặc ARN workflow **Standard** đã được TV4 tạo.
4. Lab có cho phép Lambda, SQS, DynamoDB, Step Functions, CloudWatch, tạo alarm,
   `iam:PassRole` và S3 event notification hay không.
5. SNS topic ARN cho alarm, nếu có. Để `alarm_actions=[]` thì có alarm nhưng chưa gửi thông báo.

Không giả định role tên LabRole dùng được cho cả Lambda lẫn Step Functions.
Role Lambda hiện có phải cho phép đọc `uploads/*`, đọc/cập nhật Documents,
gửi/đọc/xóa message trên đúng queue, StartExecution/DescribeExecution và ghi log.
Quyền cần thiết được liệt kê trong `infra/modules/tv2/main.tf`. Nếu Academy không cho sửa role,
giữ `manage_iam_policies=false` và nhờ giảng viên/TV5 xác nhận quyền hiện có.
Role của người chạy smoke test còn cần PutItem/S3 PutObject và quyền đọc trạng thái.

Credentials tạm (Access Key, Secret Key, Session Token) chỉ nhập **trên máy của bạn** theo hướng dẫn lab,
ở file `%USERPROFILE%\.aws\credentials` ngoài repo. Cấu hình region/profile trong `.aws/config`.
Không gửi ba giá trị này cho người khác hoặc đặt trong tfvars/Markdown/Git.
AWS CLI chưa được cài trong phiên triển khai; các script Python dưới đây có thể dùng shared profile trực tiếp.

```powershell
.\.venv\Scripts\python.exe scripts\tv2_identity.py --profile academy-lab --region REGION_CUA_LAB
```

Lệnh chỉ gọi STS để in Account ID, ARN định danh và region; không in key.
Nếu có ExpiredToken thì lấy bộ credentials mới từ lab. Không tự tạo IAM user dài hạn trong Academy.

Probe chỉ đọc quyền dịch vụ và tìm role Step Functions:

```powershell
.\.venv\Scripts\python.exe scripts\tv2_probe.py --profile academy-lab --region REGION_CUA_LAB
```

Probe đọc hết các trang IAM roles và phân tích trust policy có cấu trúc:
`step_functions_role_candidates` liệt kê ứng viên có Allow phù hợp;
`step_functions_roles_needing_review` giữ các policy có Condition/Deny hoặc quy tắc phức tạp để TV5 xác minh.
Đây không phải kiểm tra quyền IAM hiệu lực. `READ_OK` chỉ xác nhận API liệt kê đọc được,
không chứng minh quyền tạo tài nguyên hay quyền runtime. Bản probe đã sửa cần chạy lại với session lab hợp lệ.

## 4. Terraform local và môi trường dev

`infra/modules/tv2` là module để TV5 ghép với bucket/table/workflow có sẵn.
Mặc định module không sửa policy role hoặc notification của bucket hiện có.

`infra/tv2-dev` dựng môi trường TV2 độc lập: bucket upload private, bảng Documents,
ba queue, hai Lambda, log group, alarm và Standard workflow giả chỉ nhận input.
Workflow giả không gọi Textract và không đổi `QUEUED → PROCESSING`; TV4 thay bằng workflow thật sau.
Hạ tầng này chưa được deploy. Terraform dùng role có sẵn, không tự tạo IAM role.

```powershell
.\scripts\install_terraform.ps1
$tf = ".\.tools\terraform\1.13.5\terraform.exe"
& $tf fmt -check -recursive infra
& $tf -chdir=infra/tv2-dev init -backend=false
& $tf -chdir=infra/tv2-dev validate
& $tf -chdir=infra/tv2-dev test
```

`terraform test` dùng `mock_provider "aws"` và `command=plan`: không tạo tài nguyên.
Nó kiểm tra Standard workflow, timeout/visibility, DLQ, partial batch và mặc định hạn chế sửa role/bucket.
Terraform binary được tải từ HashiCorp, kiểm tra SHA256; provider đã chọn được ghi trong lock file.

Khi đã có thông tin lab, sao chép `terraform.tfvars.example` thành `terraform.tfvars`,
điền region/account/role. tfvars chỉ chứa định danh, không chứa credentials.
Xác minh đúng account bằng `tv2_identity.py`. Đặt `enable_processing=true` khi role/workflow đã sẵn sàng.
Provider giới hạn `allowed_account_ids` để chặn chạy nhầm account.

```powershell
& $tf -chdir=infra/tv2-dev plan -out tv2.tfplan
# Đọc plan, xác nhận đúng dev account và tài nguyên trước khi áp dụng.
& $tf -chdir=infra/tv2-dev apply tv2.tfplan
& $tf -chdir=infra/tv2-dev output -json tv2_config |
    Out-File -Encoding utf8 build\tv2\aws-dev.json
```

Nếu TV5 đã tạo hạ tầng cùng tên, phải ghép module/import tài nguyên đúng cách,
không apply thêm root dev để tránh xung đột. Chỉ một Terraform resource quản lý notification mỗi bucket.
`manage_iam_policies=true` chỉ dùng khi lab cho phép chỉnh role; role dùng chung không đem lại
phân tách quyền giữa hai Lambda như thiết kế production.

## 5. Kiểm tra môi trường và smoke test thật

```powershell
.\.venv\Scripts\python.exe scripts\tv2_preflight.py --config build\tv2\aws-dev.json --profile academy-lab
```

Preflight chỉ gọi API đọc: đối chiếu account/region, PK/SK đều kiểu String, Standard workflow,
env/handler, queue/DLQ/retention/visibility, mapping enabled + partial batch và failure destination.
Check `validate_max_file_size` yêu cầu đúng giới hạn contract hiện tại 10485760 byte;
không đặt env thì dùng mặc định 10 MiB của Validate. Muốn đổi giới hạn cần nhóm chốt lại contract,
Terraform và các ca smoke tương ứng trước khi sử dụng.
S3 notification phải nhận mọi `ObjectCreated` dưới `uploads/`, không thêm suffix filter:
PDF/JPG/PNG phải được xử lý và file sai đuôi cũng phải tới Validate để ghi REJECTED.
Script không poll queue, không invoke Lambda, không tạo dữ liệu. Preflight không thay thế kiểm tra IAM runtime.

Chuẩn bị `tests/samples/demo.pdf`, `demo.jpg`, `demo.png` là tài liệu giả/đã ẩn danh, thực sự đọc được,
khác 0 và tối đa 10 MiB. Chỉ khi đúng dev lab và preflight xanh:

```powershell
.\.venv\Scripts\python.exe scripts\tv2_smoke.py --config build\tv2\aws-dev.json --samples tests\samples --profile academy-lab --confirm-dev-write
```

Script tạo record/document_id mới và upload 7 ca: PDF/JPG/PNG hợp lệ, sai đuôi, rỗng,
sai chữ ký, quá lớn. Nó kiểm tra DDB và đúng 11 trường input workflow theo kiểu/giá trị;
ETag kỳ vọng lấy từ response upload S3, không tự suy ra MD5. Input thiếu/thừa trường hoặc sai dữ liệu đều không đạt;
report chỉ lưu tên trường không khớp, không chép nguyên input vào log. Ca REJECTED phải không có execution.
`input_mismatch_fields` dùng `$` cho JSON lỗi/không phải object, `$extra` cho trường dư;
report có `scope=tv2_ingestion`, `ocr_verified=false` để không nhầm với nghiệm thu OCR của TV3/TV4.
Bằng chứng và danh sách tài nguyên thử ở `build/tv2/smoke-<run_id>.json`.
Đây là kiểm tra nhận tài liệu đến workflow; execution đã bắt đầu mà OCR sau đó FAILED
được báo riêng và không chứng minh phần TV3/TV4 thành công.
Không tự xóa dữ liệu thử, để giữ bằng chứng và tránh xóa nhầm upload khác.

Các ca **phải làm thêm trên AWS** theo test matrix: hai event gọi gần đồng thời,
message độc/sai schema → DLQ sau retry, batch lỗi một phần trên event source mapping,
Validate failure destination, alarm chuyển ALARM và gửi SNS, redrive sau sửa lỗi,
10–20 upload gần đồng thời, API/presigned upload của TV1 và workflow thật TV4.
Các ca fault injection chỉ chạy trên môi trường dev riêng có thể khôi phục.

## 6. Retry và phục hồi

- File không hợp lệ: Documents REJECTED, giữ lý do; không enqueue.
- Validate lỗi SDK/record/key: Lambda async retry 2 lần, max age 3600s;
  invocation lỗi hết lượt đi vào `validate-failures`. Theo dõi cả DestinationDeliveryFailures.
- SQS có thể đến trước khi Validate ghi QUEUED: Starter trả partial failure để nhận lại sau visibility.
- Starter lỗi: chỉ retry messageId lỗi, maxReceiveCount=5, Processing DLQ giữ 14 ngày.
  Không có giao dịch nguyên tử SQS + DynamoDB; lỗi kéo dài vẫn cần xử lý thủ công.
- `validate-failures` chứa envelope invocation: lấy riêng `requestPayload` gọi lại Validate sau khi sửa.
  Không đưa envelope này vào Processing queue.
- Processing DLQ chứa body message 1.0: sửa lỗi, xác minh trạng thái/key rồi redrive về Processing queue.
  Redrive không tăng attempt; xử lý lại terminal document chưa có contract, dùng document_id mới cho demo.

Gửi lại event lặp không phải cách chủ động chạy lại OCR đã hoàn tất.
Standard có thể trả cùng kết quả StartExecution cho cùng tên/input khi execution đang chạy.
Vì vậy metric `WorkflowStarted` hiện đếm request được API chấp nhận;
đếm execution mới bằng native metric `AWS/States ExecutionsStarted` và lịch sử workflow.
Sau 90 ngày tên có thể được tái sử dụng; cơ chế hiện tại không hứa exactly-once vĩnh viễn.

## 7. Log, cleanup và bàn giao

Log JSON/EMF, không ghi body, tên file, S3 key hay credential. Namespace `IDP/Ingestion` hiện dùng cho
một dev environment trong account; nếu chạy nhiều environment chung account, TV5 cần thêm dimension Environment.
Alarm đã khai báo trong Terraform, nhưng chưa có bằng chứng ALARM/SNS thật cho đến khi deploy/test.
Native alarm lỗi Lambda/workflow và hai hàng lỗi dùng 1 trong 2 kỳ một phút vượt ngưỡng 1;
alarm tuổi queue giữ ngưỡng ít nhất 300 giây ở cả 2 kỳ để phát hiện backlog kéo dài.
Không dựa vào Lambda Errors cho partial batch: xem StarterRecordFailed và DLQ.

TV1/TV4 nhận contract tại [CONTRACT.md](CONTRACT.md), fixture tại `tests/fixtures`,
test matrix/trạng thái tại [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).
Nội dung PR chuẩn bị ở [PR_DESCRIPTION.md](PR_DESCRIPTION.md).
Nhánh bàn giao là `feature/tv2-ingestion-aws-handoff`. Checklist PROGRESS chưa đánh dấu [x]
vì chưa hoàn tất tiêu chí kiểm thử AWS và merge vào main; việc có nhánh Git không thay thế các tiêu chí đó.

Sau demo, đối chiếu manifest smoke và chỉ dọn object/record test tương ứng bằng quyền được phép;
không xóa toàn bucket hoặc các document khác. TV5 kiểm tra lại queue/workflow/log và chi phí.
Root dev đặt `force_destroy=false`: bucket còn dữ liệu sẽ chặn destroy; cần dọn đúng dữ liệu đã xác minh
và đọc `terraform plan -destroy` trước khi xóa dev stack. Khi rollback code, giữ artifact/manifest phiên bản
trước rồi cập nhật ZIP qua Terraform; tạm disable event source mapping nếu cần dừng tiêu thụ.

Giới hạn: kiểm tra chữ ký không phát hiện mọi file hỏng/malware; TV3/TV4 xử lý lỗi Textract.
Key hiện phải dùng cho một lần upload, không ghi đè. IfMatch chỉ bảo vệ lần đọc Validate, không giữ
phiên bản cho OCR về sau; cần chốt versionId xuyên pipeline nếu cho phép ghi đè.
Step Functions history có input; hạn chế quyền đọc và không bật log nguyên execution data chứa PII.

## 8. Phân biệt dữ liệu mẫu và bằng chứng thực tế

`tests/fixtures/*.json`, `tests/helpers.py`, response giả trong unit test và ARN/account trong
Terraform mock test là dữ liệu tự dựng để kiểm tra code. Các số tiền trong `docs/data-model.md`
chỉ minh họa schema, không phải kết quả OCR. Giữ dữ liệu này trong test; không trình bày nó như log AWS thật.

Số test đạt là kết quả chạy thực tế trên máy, ghi tại `build/tv2/test-results.xml`;
ca 20 tài liệu là Moto chạy local, không phải đo tải đồng thời trên AWS. SHA256/bytes của ZIP
được tính khi build và ghi tại `build/tv2/manifest.json`. Không dùng các giá trị này để suy ra p95,
chi phí hay độ chính xác OCR. Những số đo đó hiện chưa có và được giữ chờ trong bảng trạng thái.

Tên/ARN thật trong `aws-dev.example.json` tiếp tục để trống đến khi TV4/TV5 cung cấp.
Các phần còn phụ thuộc thành viên khác được liệt kê tại
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#phụ-thuộc-liên-thành-viên-còn-chờ).
