# TV2 — đối chiếu đầy đủ với hướng dẫn

Cập nhật 08/11/2026. Nhánh bàn giao `feature/tv2-ingestion-aws-handoff`.
Người phụ trách TV2 đã chọn triển khai contract đề xuất; người dùng xác nhận **chưa có hạ tầng**.
Hiện hoàn thành phần local và cấu hình chuẩn bị deploy. Chưa xác nhận hoàn thành toàn bộ nhiệm vụ AWS.
Nhóm tạm làm local theo TV5. Bản bàn giao tiếp nối commit `19eef25`;
cập nhật ngày 08/11 bổ sung các sửa lỗi review và test hồi quy bên dưới, giữ các bước AWS chờ xác minh.

## Bằng chứng local đã chạy sau khi sửa review

| Kiểm tra | Kết quả thực tế |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q --junitxml=build/tv2/test-results.xml` | 245 passed, 0 failures, 0 errors, 0 skipped; đọc lại từ XML: 143 test runtime/integration và 102 test tooling |
| `.venv/Scripts/python.exe -m pip check` | No broken requirements found |
| Moto S3 → Validate → SQS → Starter → Standard | 4 ca đạt: 1/20 tài liệu với tên thông thường hoặc bắt đầu bằng dấu chấm; mỗi document một execution dù replay; không phải test tải đồng thời AWS |
| Build hai Lambda ZIP kèm SDK | Thành công; đối chiếu source, CRC, SHA256/kích thước với `build/tv2/manifest.json`; import từng ZIP bằng Python 3.13 với `-S` không dùng site-packages đều đạt |
| Terraform 1.13.5 / hashicorp/aws 6.72.0 | Tải cục bộ; SHA256 binary và chữ ký provider đã được kiểm tra |
| `terraform -chdir=infra/tv2-dev validate` | Success! The configuration is valid |
| `terraform -chdir=infra/tv2-dev test` | 5 passed, 0 failed; tất cả dùng mock provider và plan, không gọi AWS; có ARN không qualifier, alias và version |
| Preflight chạy với config mẫu còn trống | BLOCKED rõ tên các trường thiếu, chưa truy cập AWS |
| Preflight sau review | 36 test đạt; kiểm tra suffix filter, PK/SK String, giới hạn 10485760 byte, partial batch trên mọi mapping đang bật và visibility gồm batch window; thiếu env dùng mặc định runtime |
| Probe sau review | 17 test đạt với response IAM tự dựng; đọc hết trang, phân loại ứng viên/cần kiểm tra thay vì khẳng định role dùng được |
| Smoke tooling sau review | 49 test đạt với client/file tự dựng và đồng hồ giả trong thư mục tạm; kiểm tra input, giữ lỗi đã thấy và quét cuối sau deadline kể cả API chậm; không chạy smoke lên AWS thật |
| Alarm sau review | Mock plan xác nhận lỗi/hàng lỗi dùng 1/2 kỳ; tuổi queue dùng 2/2 kỳ với ngưỡng 300 giây |

## Lịch sử kiểm tra AWS ở phiên trước

Các dòng dưới ghi lại phiên lab ngày 07/11/2026. Lượt sửa local này không gọi API AWS thật,
không tạo tài nguyên và không kiểm tra lại credentials/quyền/trạng thái tài nguyên hiện tại.

| Kiểm tra trước đây | Kết quả ghi nhận trong phiên đó |
| --- | --- |
| Profile `academy-lab` / STS | Xác nhận account Sandbox, region `us-east-1` và identity tạm `assumed-role/voclabs/...`; account ID/ARN cũ không dùng làm cấu hình TV5, không ghi credential vào repo/log |
| Probe chỉ đọc Cloud Foundations Sandbox | Các API liệt kê của S3, DynamoDB, SQS, Lambda, Step Functions và CloudWatch đọc được; chưa có role Step Functions đã xác minh dùng được. Cần chạy lại probe đã sửa trong session hợp lệ |
| Terraform plan AWS thật | 30 add, 0 change, 0 destroy; consumer SQS tắt và workflow để trạng thái chờ TV4 |
| Terraform apply AWS thật | Bị policy lab chặn: thiếu `dynamodb:CreateTable` và explicit deny `s3:GetBucketObjectLockConfiguration` |
| Khôi phục apply dang dở | Chỉ một bucket rỗng đã kịp tạo; destroy-plan 0 add/0 change/1 destroy đã chạy thành công, Terraform state trở lại trống |

Test Python chạy bằng Python 3.13.14 trên máy hiện tại. Runtime dự kiến Lambda là 3.12;
ZIP chọn wheel Linux/Python 3.12, nhưng chưa có kiểm thử runtime Lambda thật.
Test Moto dùng dữ liệu giả/magic bytes; cần mẫu PDF/JPG/PNG ẩn danh thực sự đọc được để test AWS/OCR.

## Trạng thái từng bước

| Bước trong hướng dẫn | Đã triển khai / bằng chứng | Phần còn cần |
| --- | --- | --- |
| Giai đoạn 0 — contract | [CONTRACT.md](CONTRACT.md), người phụ trách TV2 chọn phương án | TV1/TV4/TV5 xác nhận liên thông, quyền lab, region và chính sách ghi đè |
| 0 — môi trường | Branch riêng, `.venv`, Python/SDK/pytest/Moto, Terraform cục bộ; profile/STS/account/region của lab đã xác minh | AWS CLI chưa cài nhưng boto3/Terraform dùng được shared profile; credentials hết hạn theo phiên lab |
| 1 — cấu trúc/dependency | Hai thư mục Lambda, test/fixture/scripts, requirements, gitignore, README; thay hai .gitkeep bằng mã; chuẩn bị bàn giao trên nhánh riêng | TV5 nhận nhánh và chạy lại trong môi trường của mình; chờ review/merge |
| 2 — config/log/S3 event/key | `config.py`, `observability.py`, `s3_event.py`; decode Unicode/+, kiểm tra key/control char | Trigger S3 thật |
| 3 — quy tắc file | PDF/JPG/JPEG/PNG, magic bytes, rỗng, giới hạn, document_type, mã reject; test boundary | Nhóm xác nhận max trang/không hỗ trợ TIFF; TV3 chịu xử lý file hỏng sâu |
| 4 — message/DynamoDB | `messages.py`, `repository.py`, sample JSON; GetItem consistent, update status có điều kiện | Sample SQS lấy từ AWS; TV1 tạo record trước upload |
| 5 — Validate | Metadata/ETag/IfMatch, kiểm tra record, REJECTED không enqueue, SQS trước QUEUED, duplicate an toàn | IAM thật, S3 object bất biến hoặc phương án versionId |
| 6 — unit test | Bộ test gốc và nhánh lỗi đã chạy trong repo | Chạy lại trong CI/3.12 nếu nhóm dùng runtime chính xác |
| 7 — Workflow Starter | Schema/record/status, pending retry, tên/input xác định, xác minh AlreadyExists, partial batch | State machine Standard thật; quyền StartExecution/DescribeExecution |
| 8 — yêu cầu TV5/Terraform | Module tái sử dụng + root dev, dùng role có sẵn, 3 queue, Lambda, IAM tùy chọn, mapping, notification, alarm; validate/mock plans pass; plan AWS thật 30/0/0 | Cần lab/role khác cho phép CreateTable và Terraform đọc cấu hình bucket; cần role trust Step Functions hoặc workflow TV4 |
| 9 — kết nối AWS | Identity và probe chỉ đọc đã chạy trên account/region thật; [runbook](README.md), preflight/smoke scripts sẵn sàng | Cloud Foundations Sandbox hiện tại không đủ quyền để dựng hạ tầng; chưa thể chạy preflight/smoke thật |
| 10 — retry/DLQ/redrive | Cấu hình visibility180s, maxReceive5, retention4/14ngày, async retry2/maxage3600; runbook hai envelope riêng | Fault injection, message về DLQ, redrive phục hồi trên AWS thật |
| 11 — test matrix | Unit + Moto integration 1/20 file, valid/reject/duplicate/SDK failure/partial batch/log không PII | AWS PDF/JPG/PNG, upload gần đồng thời, p95, quota/chi phí, lỗi hạ tầng và event lặp thật |
| 12 — log/metric/alarm | JSON/EMF + Terraform alarm, log retention14ngày; metric lỗi riêng cho partial batch | Alarm transitions, SNS topic/subscription/nhận thông báo, dashboard/chi phí với TV5 |
| 13 — bàn giao/PR/PROGRESS | Contract, ba fixture đồng nhất, runbook, PR description; commit `19eef25` đã bàn giao, bản cập nhật local ngày 08/11 bổ sung sửa lỗi review trên cùng nhánh | TV1/TV4/TV5 xác nhận contract và nhận bàn giao local; PR/review/merge; message/input/log AWS để giai đoạn sau |
| Phụ lục — lỗi/vấn đáp/giới hạn | Các lỗi thường gặp trong guide + runbook; mô tả race, quota, retention, retry và giới hạn chữ ký | Không suy ra production-ready/exactly-once vĩnh viễn từ test local |

## Test matrix còn phải kiểm chứng trên AWS

- [ ] Academy session, account/region và role permissions/trust được xác minh.
- [ ] S3 notification tự gọi Validate và event source mapping tự tiêu thụ SQS.
- [ ] PDF, JPG/JPEG, PNG cho cả INVOICE/TRANSCRIPT → một Standard execution.
- [ ] Sai đuôi, 0 byte, >10 MiB, sai magic bytes → REJECTED đúng reason và không execution.
- [ ] Unicode/khoảng trắng/dấu + trong key; event S3/SQS lặp và gọi gần đồng thời.
- [ ] Race SQS trước QUEUED, message lỗi trong batch chỉ retry chính nó.
- [ ] Validate thiếu record/IAM/object lỗi → validate-failures đúng envelope.
- [ ] Starter lỗi schema/IAM/quota → Processing DLQ sau nhiều lần nhận.
- [ ] Sửa lỗi + redrive đúng hàng, chứng minh không OCR trùng.
- [ ] Queue backlog/DLQ/custom/Lambda/workflow alarm và nhận SNS thông báo.
- [ ] 10–20 upload gần đồng thời: không mất tài liệu, ghi p95 và chi phí.
- [ ] API/presigned URL TV1, quyền user A/B, URL hết hạn và workflow thật TV4/TV3.
- [ ] Lưu bằng chứng đã ẩn danh, TV4 xác nhận input, PR merge, cập nhật checklist hoàn tất.

Các ô `[ ]` ở đây là việc chưa có bằng chứng AWS, không phải nội dung bị bỏ qua.
PROGRESS định nghĩa `[x]` là đã test và merge; các ô tổng của dự án được giữ nguyên.

## Sửa mẫu hướng dẫn khi đưa vào mã thật

- Pin SDK và dependency runtime thay vì để requirements rỗng; hai ZIP độc lập cho Python3.12/Linux.
- Chặn event bucket sai (nếu set UPLOAD_BUCKET), ID/filename có control char, message MIME sai;
  không ghi reject_detail/file key/tên file vào log; che thông điệp SDK trong traceback Lambda.
- Xác minh mock-plan hạ tầng thay vì coi đoạn Terraform minh họa là deploy được ngay.
- Preflight yêu cầu notification chỉ có prefix `uploads/`, không có suffix; xác minh PK/SK kiểu String.
- Native alarm lỗi và hàng lỗi dùng 1/2 kỳ để bắt lỗi đơn lẻ; alarm backlog giữ 2/2 kỳ.
- `WorkflowStarted` là số StartExecution được chấp nhận, có thể gồm idempotent retry đang chạy;
  muốn đếm workflow mới phải dùng native ExecutionsStarted/lịch sử execution.
- Starter lấy đuôi từ dấu chấm cuối giống Validate, tránh kẹt QUEUED với tên `.pdf`/`.jpg`/`.png`.
- Smoke đối chiếu đủ 11 trường theo tên/kiểu/giá trị, lấy ETag từ PutObject và báo tên trường sai;
  `scope=tv2_ingestion`, `ocr_verified=false` phân biệt tiếp nhận thành công với kết quả OCR.
- Probe dùng paginator và cấu trúc Effect/Action/Principal; trường hợp Condition/Deny/phức tạp
  được chuyển sang danh sách cần TV5 kiểm tra, không tự suy ra quyền IAM hiệu lực.

Trong lần cleanup trước, bucket rỗng tạo dang dở đã được xóa và Terraform state trở lại trống;
đây không phải xác nhận lại tài nguyên AWS hiện tại.

## Sửa tiếp sau rà soát sâu ngày 08/11

- SQS JSON escape U+FFFE/U+FFFF mà không đổi key sau decode; test thêm bộ kiểm tra ký tự
  theo ràng buộc AWS vì Moto chưa thực thi ràng buộc đó.
- Xác minh execution cũ bằng JSON chuẩn hóa có phân biệt kiểu; không ACK input `attempt=true/1.0`
  khi message hiện tại có `attempt=1`, vẫn chấp nhận khác whitespace/thứ tự trường.
- IAM StartExecution dùng ARN workflow gốc, thêm qualifier condition cho alias/version;
  test riêng ARN không qualifier, alias và version bằng mock plan.
- Preflight tính cả batch window, yêu cầu mọi mapping liên quan đang bật có partial batch.
- Smoke quan sát hết cửa sổ sau upload và có vòng quét cuối bắt đầu tại/sau deadline;
  giữ lỗi đã quan sát, ghi thời lượng thực tế, không khẳng định không có execution vĩnh viễn.
- Root dev yêu cầu Terraform từ 1.11 cho test plan-time override; helper vẫn là 1.13.5.
- Đồng bộ ba fixture cùng một object Unicode; bảng bàn giao ghi đúng commit/push đã có.

Các khoảng trống vẫn để chờ: chạy runtime Python 3.12, worker thực sự đồng thời, Lambda hết timeout,
vòng đời retry/DLQ/redrive và tích hợp/persistence của TV4. Không tính các mục này là đã đạt từ test local.

## Số liệu mẫu và số liệu chưa có

| Nội dung | Nguồn và giới hạn sử dụng |
| --- | --- |
| `tests/fixtures/*.json`: size 52341, ETag, ID, bucket, timestamp | Dữ liệu tự dựng để kiểm tra schema, không phải event/message/execution AWS đã thu |
| `tests/helpers.py`, các response trong test Python và Terraform mock | Byte/định danh/trạng thái tự dựng; không chứng minh đọc được tài liệu, IAM hay Textract thật |
| Tiền/số lượng trong `docs/data-model.md` | Ví dụ schema, không phải số liệu hóa đơn hoặc kết quả OCR đã xác minh |
| 245 test Python và 5 mock plan | Kết quả thực tế của lệnh local, không phải số lượt xử lý trên AWS |
| SHA256/kích thước hai ZIP | Tính từ artifact build; xem `build/tv2/manifest.json`, không tự điền giá trị minh họa |
| 10 MiB, visibility 180s, concurrency 5, ngưỡng alarm | Tham số cấu hình đề xuất, chưa phải kết quả đo hiệu năng |
| p95 AWS, chi phí, độ chính xác OCR, thông lượng AWS | **CHƯA ĐO**; chưa điền số 0 hoặc số ước lượng thành kết quả |
| Message/input/log bàn giao từ AWS thật | **CHƯA THU**; fixture chỉ là mẫu cho các thành viên phát triển song song |

## Phụ thuộc liên thành viên còn chờ

| Thành viên | Phần để chờ xác nhận/cung cấp, TV2 không tự điền thay |
| --- | --- |
| TV1 | API/presigned URL thật, tạo UPLOAD_PENDING trước upload, xác thực user/key và UI map reject_reason; chính sách không ghi đè key |
| TV3 | Mẫu PDF/JPG/PNG đã ẩn danh thực sự đọc được, giới hạn số trang, Textract/parser và kết quả OCR thật |
| TV4 | Xác nhận PK/SK/GSI, Standard workflow ARN thật, nhận đủ 11 trường, conditional QUEUED → PROCESSING và trạng thái/kết quả tiếp theo; JobCallbacks/reprocess nếu cần |
| TV5 | Môi trường/quyền phù hợp, ghép Terraform module, IAM/notification/SQS mapping, CI/CD, SNS/alarm và bằng chứng vận hành thật |

Giữ `docs/tv2/aws-dev.example.json` trống ở các định danh chưa được cung cấp.
Checklist AWS và PROGRESS chưa đánh dấu hoàn tất; nhánh bàn giao chưa đồng nghĩa đã merge hoặc đã chạy AWS thật.
