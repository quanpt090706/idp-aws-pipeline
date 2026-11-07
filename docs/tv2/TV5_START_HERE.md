# TV2 + TV5 — bắt đầu chạy AWS thật

Đã thống nhất: chạy trên máy TV5, dùng profile của TV5; hiện chưa có hạ tầng.
Loại lab, account, region và quyền hiệu lực vẫn cần kiểm tra. Chưa chạy deploy hoặc smoke lên AWS.

## 1. Nhận đúng bản TV2

Nhánh bàn giao: `feature/tv2-ingestion-aws-handoff`. TV5 có thể clone vào thư mục riêng
để không chép đè phần đang làm:

```powershell
git clone --branch feature/tv2-ingestion-aws-handoff --single-branch https://github.com/quanpt090706/idp-aws-pipeline.git idp-aws-pipeline-tv2
Set-Location -LiteralPath idp-aws-pipeline-tv2
```

Git chứa source TV2, tests, Terraform và tài liệu; không chứa `.venv`, ZIP build, credentials,
Terraform state/tfvars thật hoặc mẫu tài liệu cá nhân. TV5 tạo artifact/báo cáo trên máy mình bằng các lệnh dưới.
Nếu nhận gói ZIP bàn giao local trước đây thì giải nén vào thư mục riêng và đối chiếu với nhánh;
gói đó có hai Lambda ZIP và báo cáo test local nhưng không thay thế việc review/merge.

Mở terminal PowerShell tại gốc repo có `requirements-dev.txt`.
Nếu máy TV5 dùng hệ điều hành khác Windows, cần đổi đường dẫn Python và cách cài Terraform tương ứng.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --junitxml=build/tv2/test-results.xml
.\.venv\Scripts\python.exe scripts\build_tv2.py
```

Không tạo lại venv nếu TV5 đã có môi trường phù hợp. Python 3.12 được ưu tiên vì trùng Lambda;
kết quả local của TV2 trước bàn giao chạy trên Python 3.13.14. Các test SDK được giả lập, không gọi AWS thật.
Lệnh build tạo hai ZIP kèm dependency cho Lambda Linux x86_64/Python 3.12;
nếu sửa source sau đó thì build lại bằng `scripts/build_tv2.py`.

## 2. Start Lab và kiểm tra chỉ đọc

TV5 Start Lab và ghi lại tên loại lab (Cloud Foundations Sandbox/Learner Lab/khác).
Mở AWS Console để kiểm tra account và region được lab cho phép. Nếu lab cấp credentials tạm,
TV5 cập nhật profile trên máy mình theo hướng dẫn của lab, không gửi key/token trong chat hoặc repo.

Hai lệnh dưới hỏi tên profile và region thật, không có account/resource giả để copy nhầm:

```powershell
$tv5Profile = Read-Host "Ten profile AWS tren may TV5"
$tv5Region = Read-Host "Region duoc lab cho phep"
.\.venv\Scripts\python.exe scripts\tv2_identity.py --profile $tv5Profile --region $tv5Region
.\.venv\Scripts\python.exe scripts\tv2_probe.py --profile $tv5Profile --region $tv5Region
```

Gửi TV2: loại lab và toàn bộ JSON kết quả hai lệnh trên. Các script không in credentials.
Nếu identity báo BLOCKED, sửa lỗi phiên/profile trước; chưa deploy. Đối chiếu account trả về với Console.
`READ_OK` chỉ là API liệt kê đọc được, không chứng minh quyền tạo tài nguyên.
`step_functions_role_candidates` là ứng viên; `step_functions_roles_needing_review` cần xem trust policy,
Condition/Deny và quyền dịch vụ. Danh sách trống hoặc IAM list bị từ chối không chứng minh role dùng được.

## 3. Quyết định khả thi trước khi apply

TV5/giảng viên cần xác nhận quyền tạo bucket, Documents, Lambda/SQS/log/alarm, cấu hình notification,
PassRole và workflow Standard; đồng thời xác nhận role Lambda và role Step Functions dùng được.
Role có quyền đọc không đồng nghĩa được tạo tài nguyên. Terraform plan cũng chưa chứng minh apply sẽ thành công.

| Kết quả kiểm tra thực tế | Cách tiếp tục |
| --- | --- |
| Đủ quyền tạo mới và có các execution role phù hợp | Dùng root `infra/tv2-dev` cho môi trường riêng; mock workflow chỉ kiểm tra ingestion, không làm OCR |
| TV4/TV5/giảng viên cấp sẵn bucket, bảng và Standard workflow | Ghép `infra/modules/tv2` với đúng tên/ARN; không apply root dev để tạo thêm tài nguyên trùng |
| Terraform bị deny đọc Object Lock nhưng bucket có thể được cấp sẵn | TV5 cân nhắc module dùng bucket có sẵn, không quản lý bucket đó bằng resource tạo mới; vẫn cần kiểm tra các quyền khác |
| CreateTable bị deny và không có Documents phù hợp | Chờ giảng viên/môi trường khác cấp bảng; không bỏ DynamoDB rồi coi như pipeline gốc đã đạt |
| Không có role/workflow Step Functions dùng được | Nhờ TV4/TV5/giảng viên cấp; nếu chỉ demo đoạn trước workflow thì phải thống nhất và ghi rõ phạm vi chưa đạt |
| Lab vẫn chặn các dịch vụ bắt buộc | Đổi sang môi trường được giảng viên cấp quyền phù hợp; giữ test local trong lúc chờ, chưa ghi nhận số liệu AWS |

Không thay contract TV1/TV3/TV4 hoặc bỏ bước xử lý chỉ để làm báo cáo xanh.
Nếu phải đổi kiến trúc, nhóm cần thống nhất phạm vi và phần bàn giao bị ảnh hưởng trước khi sửa.

## 4. Khi đã đủ điều kiện triển khai

Làm theo [README.md](README.md), mục Terraform và preflight; không chạy saved plan của phiên/account cũ.
Điền account/region/role thật từ bước 2–3 vào cấu hình local và giữ các ARN chưa được cung cấp ở trạng thái chờ.
Root dev mặc định tắt consumer SQS; chỉ bật khi role, workflow và contract đã sẵn sàng.
Đọc plan mới, xác nhận đúng account/tài nguyên trước apply. Nếu apply lỗi, ghi lại lỗi và tài nguyên đã tạo;
TV2/TV5 đối chiếu state trước khi thử lại hoặc dọn phần dang dở.

Sau deploy, dùng output thật để tạo `build/tv2/aws-dev.json` theo
[aws-dev.example.json](aws-dev.example.json), rồi chạy preflight. Nếu có check FAIL/BLOCKED, sửa đúng nguyên nhân trước smoke.
Không dùng preflight khi chưa có tài nguyên vì các API describe cần đối tượng thật.

## 5. Thu bằng chứng thật

TV3/nhóm cung cấp `tests/samples/demo.pdf`, `demo.jpg`, `demo.png` đã ẩn danh và thực sự đọc được.
Không lấy byte giả trong `tests/helpers.py` làm mẫu OCR.

```powershell
.\.venv\Scripts\python.exe scripts\tv2_preflight.py --config build\tv2\aws-dev.json --profile $tv5Profile
# Chỉ chạy dòng sau khi preflight PASS, đúng dev account và nhóm sẵn sàng tạo dữ liệu thử.
.\.venv\Scripts\python.exe scripts\tv2_smoke.py --config build\tv2\aws-dev.json --samples tests\samples --profile $tv5Profile --confirm-dev-write
```

Smoke tạo dữ liệu thử, kiểm tra 7 ca và lưu báo cáo thật tại `build/tv2/smoke-<run_id>.json`.
Giữ report, thời gian/account/region, log đã ẩn danh, trạng thái Documents và execution tương ứng.
Report chỉ chứng minh `tv2_ingestion`, luôn ghi `ocr_verified=false`; mock workflow không chứng minh Textract/parser.
Các ca retry/DLQ/redrive, event lặp/đồng thời, alarm/SNS và luồng API TV1 vẫn phải test theo
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). p95/chi phí/độ chính xác OCR để CHƯA ĐO đến khi có phép đo thật;
không suy ra các số đó từ số test local hoặc từ một lần smoke.
