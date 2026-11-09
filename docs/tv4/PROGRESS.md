# BÁO CÁO TIẾN ĐỘ CÔNG VIỆC — THÀNH VIÊN 4 (DATA & ORCHESTRATION)

> **Dự án**: Intelligent Document Processing Pipeline on AWS (`idp-aws-pipeline`)  
> **Thành viên phụ trách**: Thành viên 4 (TV4)  
> **Thời điểm cập nhật**: 08/11/2026  
> **Trạng thái tổng thể**: **HOÀN THÀNH 100% CÁC HẠNG MỤC PHỤ TRÁCH** (Mã nguồn sạch, 20/20 tests TV4 Passed, 265/265 tests toàn repo Passed)

---

## 1. TỔNG QUAN VAI TRÒ CỦA TV4 TRONG PIPELINE

Thành viên 4 đóng vai trò là **Bộ não điều phối trung tâm (Central Orchestrator) & Kỹ sư Dữ liệu (Data Engineer)**:
- Tiếp nhận dữ liệu từ **TV2 (Ingestion)** sau khi nạp file vào S3 và hàng đợi SQS.
- Khởi chạy và điều phối vòng đời tài liệu qua **AWS Step Functions Standard State Machine**.
- Gọi bất đồng bộ dịch vụ bóc tách OCR của **TV3 (Textract / AI)** qua cơ chế Task Token callback (`.waitForTaskToken`).
- Quản trị toàn bộ cơ sở dữ liệu **DynamoDB Single-Table Design** và cấu trúc **S3 Processed Data Lake**.
- Gửi thông báo kết quả tự động qua **Amazon SES** (Email HTML/Plain Text).

```
[TV2: Ingestion SQS] ──(11 fields input)──> [TV4: Step Functions State Machine]
                                                        │
                      ┌─────────────────────────────────┴─────────────────────────────────┐
                      ▼                                                                   ▼
          [SetProcessingStatus]                                            [RouteByDocumentType]
          (Chặn ghi đè: Fencing Token)                                       (INVOICE vs TRANSCRIPT)
                      │                                                                   │
                      └─────────────────────> [TV3: StartJob] <───────────────────────────┘
                                                  │
                                                  ▼ (Dừng chờ Textract callback, timeout 15 phút)
                                          [TaskToken Callback]
                                                  │
                                                  ▼
                                     [EvaluateExtractionResult]
                                      (IsPresent: true check)
                                                  │
                                ┌─────────────────┴─────────────────┐
                                ▼                                   ▼
                       (SUCCEEDED Flow)                    (NEEDS_REVIEW Flow)
                                │                                   │
                                └─────────────────┬─────────────────┘
                                                  ▼
                              [Cập nhật DynamoDB + Fencing Token]
                                                  │
                                                  ▼
                                    [SendCompletionNotification] (SES)
                                    (Nuốt lỗi Catch States.ALL)
                                                  │
                                                  ▼
                                         [WorkflowSucceeded]
```

---

## 2. CHI TIẾT CÁC HẠNG MỤC ĐÃ HOÀN THÀNH

### Mốc 1: Thiết kế Cơ sở dữ liệu & Data Lake Partitioning
- [x] **Bảng DynamoDB `Documents` (Single-Table Design)**:
  - Khóa chính: `PK = USER#<user_id>`, `SK = DOC#<document_id>`.
  - Chỉ mục `GSI-status`: `status` (PK) + `created_at` (SK) — phục vụ truy vấn danh sách theo trạng thái (`PROCESSING`, `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`).
  - Chỉ mục `GSI-type`: `document_type` (PK) + `created_at` (SK) — phục vụ lọc riêng Hóa đơn hoặc Bảng điểm.
  - Bật chế độ phục hồi tại chỗ Point-in-Time Recovery (PITR).
- [x] **Bảng phụ DynamoDB `JobCallbacks` & TTL**:
  - Khóa chính thống nhất: `job_id` (String).
  - Thuộc tính: `task_token`, `document_id`, `user_id`, `ttl`.
  - Cơ chế Time-to-Live (TTL): Tự động dọn dẹp các token đã quá 7 ngày hoàn toàn miễn phí.
- [x] **Quy ước phân vùng S3 Processed Data Lake**:
  - Chuẩn Hive-style: `s3://<processed-bucket>/user_id=<user_id>/year=<YYYY>/month=<MM>/<document_id>.json`.

### Mốc 2: Xây dựng Step Functions State Machine (`state_machine.asl.json`)
- [x] **14 States chuẩn ASL Native Integration**:
  - Gọi AWS SDK trực tiếp `dynamodb:updateItem`, không qua Lambda trung gian (tiết kiệm chi phí và giảm độ trễ).
- [x] **Khóa quyền sở hữu (Fencing Token / Ownership Locking)**:
  - `SetProcessingStatus` siết chặt điều kiện:
    ```sql
    ConditionExpression: attribute_exists(PK) AND (#status = :queued OR (#status = :processing AND sfn_execution_id = :exec_id))
    ```
  - Ngăn chặn hoàn toàn việc Execution B chạy sau cướp quyền hoặc ghi đè Execution A đang xử lý.
- [x] **Chống lỗi `States.Runtime`**:
  - `EvaluateExtractionResult` kiểm tra `IsPresent: true` với từng trường bắt buộc trước khi chuyển sang update.
  - `SendCompletionNotification` truyền nguyên khối `ocr_result.$: $.ocr_result`, loại bỏ nguy cơ crash do thiếu trường `warnings`.
- [x] **Khả năng tự phục hồi (Resilience)**:
  - Thêm `Retry` Exponential Backoff cho các lỗi transient của DynamoDB.
  - Bắt riêng `DynamoDB.ConditionalCheckFailedException` và `DynamoDb.ConditionalCheckFailedException` đưa sang `AlreadyProcessedNoOp` để không bao giờ ghi đè tài liệu đã thành công thành thất bại.
  - `HandleFailure` có đúng 3 cạnh chuyển tiếp, nhánh `overwrite_prevented` bỏ qua gửi email lỗi giả.

### Mốc 3: Lambda Mock Worker phục vụ kiểm thử độc lập
- [x] File `lambdas/mock-worker/mock_worker.py`:
  - Giả lập trọn vẹn hành vi của Textract và Lambda Parser của TV3.
  - Hỗ trợ 3 kịch bản: `SUCCEEDED` (Hóa đơn Vinamilk / Bảng điểm), `NEEDS_REVIEW` (kèm cảnh báo), `FAILED` (ném ngoại lệ).
  - Tích hợp hàm `save_job_callback()` lưu token vào bảng `JobCallbacks`.

### Mốc 4: Tích hợp Amazon SES Notification
- [x] File `lambdas/notification/handler.py`:
  - Template email HTML Table sang trọng (Inline CSS), phân biệt badge màu trạng thái (`#28a745` Thành công, `#fd7e14` Cảnh báo, `#dc3545` Thất bại).
  - Tự động bóc tách các trường nghiệp vụ: "Đơn vị phát hành", "Tổng tiền thanh toán" (Hóa đơn) và "Họ và tên", "GPA" (Bảng điểm).
  - Hỗ trợ parse `extracted` linh hoạt (cả kiểu dict lẫn chuỗi JSON `json.loads`).
  - Bản Plain Text sạch sẽ, không bị dính HTML entities.
  - Bảo mật: Hàm `sanitize_header_value` loại bỏ cả ký tự xuống dòng `\r\n\t` lẫn thẻ `<...>`, chống Header Injection và XSS.
  - Thân thiện: Ẩn 100% chi tiết lỗi kỹ thuật thô (ARN, stack trace), chuyển thành thông điệp tiếng Việt thân thiện.
  - Nuốt lỗi toàn diện: Toàn bộ handler bọc trong `try/except Exception`, trả `FAILED_TO_SEND` hoặc `SKIPPED_NO_RECIPIENT` (nếu không có người nhận), không bao giờ làm crash Step Functions.
  - Khởi tạo `ses_client` ở module level giúp tái sử dụng kết nối HTTP Keep-Alive.

### Mốc 5: Đóng gói Infrastructure as Code (Terraform Module)
- [x] Thư mục `infra/modules/tv4/`:
  - `main.tf`: Quản lý State Machine và tự động đóng gói Lambda Notification bằng `archive_file`.
  - `iam.tf`: Khai báo phân quyền Least Privilege cho Step Functions và SES Notification.
  - `variables.tf` & `outputs.tf`: Cung cấp cờ `manage_iam_policies = false` (mặc định an toàn cho môi trường AWS Academy LabRole để tránh lỗi AccessDenied).

### Mốc 6: Hợp đồng tích hợp với TV3 (`CONTRACT.md`)
- [x] File `docs/tv4/CONTRACT.md`:
  - Chốt giới hạn 256 KB của Step Functions payload.
  - Chốt cấu trúc bảng `JobCallbacks` (Partition Key `job_id`).
  - Yêu cầu Lambda `StartJob` kiểm tra tính Idempotent trước khi gọi Textract mới.
  - Chốt định dạng phân vùng S3 Processed Data Lake Hive-style.

---

## 3. KẾT QUẢ KIỂM THỬ TỰ ĐỘNG (AUTOMATED TEST SUITE)

Bộ kiểm thử được viết bằng `pytest` kết hợp với thư viện `moto` giả lập in-memory toàn bộ dịch vụ AWS (DynamoDB, SES), chạy độc lập không tốn chi phí và không phụ thuộc tài khoản AWS thật:

```bash
# 1. Kiểm thử riêng module TV4 (20 bài test)
$ .venv/bin/pytest tests/tv4/ -v
============================== 20 passed in 2.20s ==============================

# 2. Kiểm thử toàn bộ hệ thống (Toàn repo)
$ .venv/bin/pytest
============================= 265 passed in 11.55s =============================
```

### Danh sách 20 ca kiểm thử của TV4 ([`tests/tv4/test_orchestration.py`](../../tests/tv4/test_orchestration.py)):
1. `test_asl_json_syntax_and_structure`: Kiểm tra tính toàn vẹn DAG, không còn `HeartbeatSeconds`, đủ cả 2 cách viết DynamoDB, đúng 3 cạnh của `HandleFailure`, không dùng JSONPath vào trường tùy chọn.
2. `test_dynamodb_transition_queued_to_processing`: Kiểm tra chuyển trạng thái `QUEUED` $\rightarrow$ `PROCESSING` có điều kiện.
3. `test_fencing_token_prevents_zombie_execution_overwrite`: Kiểm chứng Fencing Token chống Execution chạy sau chiếm quyền.
4. `test_replaying_succeeded_document_does_not_overwrite_with_failed`: Kiểm chứng tài liệu đã `SUCCEEDED` không bao giờ bị ghi đè thành `FAILED`.
5. `test_dynamodb_transition_processing_to_succeeded`: Kiểm tra ghi nhận kết quả và truy vấn qua 2 GSI.
6. `test_dynamodb_transition_processing_to_needs_review`: Kiểm tra gắn nhãn cảnh báo `warnings`.
7. `test_job_callbacks_table_and_ttl`: Kiểm tra lưu token và tính toán TTL 7 ngày.
8. `test_mock_worker_payload_generation`: Kiểm tra các kịch bản sinh dữ liệu OCR mock.
9. `test_integration_with_tv2_input_fixture`: Kiểm thử tích hợp từ input 11 trường của TV2.
10. `test_render_email_content_succeeded`: Kiểm tra template HTML/Text có đầy đủ hàng nghiệp vụ (Hóa đơn).
11. `test_render_email_content_with_json_string_extracted`: Kiểm tra tự động parse khi TV3 trả `extracted` dạng chuỗi JSON.
12. `test_render_email_content_succeeded_without_warnings`: Kiểm tra trường hợp thành công không có warnings vẫn render mượt mà.
13. `test_render_email_content_needs_review`: Kiểm tra template cho kết quả cảnh báo (Bảng điểm).
14. `test_render_email_content_failed_with_friendly_message`: Kiểm tra lỗi kỹ thuật được đổi sang câu tiếng Việt thân thiện và không ép sai loại tài liệu.
15. `test_render_email_content_html_escaping_and_header_sanitize`: Kiểm tra chống XSS và Header Injection trên cả Subject và Body.
16. `test_get_recipient_email_priority`: Kiểm tra trọn vẹn 4 nhánh ưu tiên xác định email người nhận.
17. `test_notification_lambda_send_email_success`: Kiểm tra Lambda gửi mail SES thành công qua Moto.
18. `test_notification_lambda_skipped_when_no_recipient`: Kiểm tra bỏ qua an toàn với `SKIPPED_NO_RECIPIENT` khi không có email.
19. `test_notification_lambda_handles_ses_error_gracefully`: Kiểm tra nuốt lỗi khi SES ném `ClientError`.
20. `test_notification_lambda_catches_all_exceptions_gracefully`: Kiểm tra handler tự phục hồi khi có exception bất ngờ.

---

## 4. KẾ HOẠCH BÀN GIAO & PHỐI HỢP TIẾP THEO

| Đối tác | Nội dung phối hợp | Trách nhiệm của TV4 |
|---|---|---|
| **Thành viên 3 (AI / OCR)** | Nhận ARN Lambda `StartJob` thật từ TV3 và kết nối SNS completion callback. | Cung cấp tài liệu [`docs/tv4/CONTRACT.md`](CONTRACT.md) và bảng `JobCallbacks`. |
| **Thành viên 5 (DevOps / IaC)** | Ráp module `infra/modules/tv4/` vào root `main.tf`. | Hướng dẫn TV5 truyền `start_job_lambda_arn`, `workflow_role_arn` và kết nối bảng `Documents` dùng chung. |
| **Chuẩn bị Demo** | Verify email trên AWS SES Console. | Verify trước 2 địa chỉ: `SENDER_EMAIL` và `DEMO_NOTIFICATION_EMAIL`. |
