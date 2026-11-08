# TV4 — Data & Orchestration (Kế hoạch & Triển khai)

## 1. Vai trò của Thành viên 4
- **Chịu trách nhiệm**:
  - Quản lý mô hình dữ liệu (DynamoDB Single-Table Design & S3 Data Lake Partitioning).
  - Thiết kế và cài đặt State Machine trên AWS Step Functions để điều phối toàn bộ pipeline.
  - Quản lý cơ chế Task Token callback bất đồng bộ với Textract và Lambda Parse.
  - Xử lý các kịch bản lỗi, retry với Exponential Backoff, timeout và phân nhánh trạng thái (`PROCESSING`, `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`).
  - Gửi email thông báo kết quả qua Amazon SES.

## 2. Giao diện nhận bàn giao từ TV2
- **Input từ Workflow Starter**: Xem mẫu chuẩn tại [step_functions_input.json](../../tests/fixtures/step_functions_input.json).
- **Hợp đồng tích hợp**: Xem quy ước tại [docs/tv2/CONTRACT.md](../tv2/CONTRACT.md).

## 3. Các đầu việc chính
1. **State Machine Definition**: `infra/step_functions/state_machine.asl.json`
2. **DynamoDB Tables**: `Documents` và `JobCallbacks` (kèm TTL)
3. **Terraform Module TV4**: `infra/modules/tv4/`
4. **Mock Integration Tests**: Bộ test giả lập Textract callback để kiểm chứng State Machine độc lập.
