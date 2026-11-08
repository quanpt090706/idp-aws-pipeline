# HỢP ĐỒNG GIAO DIỆN & TÍCH HỢP GIỮA TV4 (ORCHESTRATION) VÀ TV3 (AI / OCR)

> **Tài liệu chuẩn mực kỹ thuật (Contract v1.0)**  
> **Người biên soạn**: Thành viên 4 (TV4 — Data & Orchestration)  
> **Bên liên quan**: Thành viên 3 (TV3 — Textract & AI Processing), Thành viên 5 (TV5 — Root IaC)

---

## 1. QUY ƯỚC LƯU TRỮ VÀ GIỚI HẠN DUNG LƯỢNG (CRITICAL CONTRACT)

### 1.1. Giới hạn 256 KB của Step Functions
- **Quy định bắt buộc**: AWS Step Functions áp dụng hard limit **256 KB** cho input/output của một State và payload gọi `sfn.send_task_success`.
- **Hành động của TV3**:
  - Toàn bộ kết quả OCR thô (Raw Blocks, Geometry, BoundingBoxes của Textract có dung lượng vài MB) **phải được ghi trực tiếp vào S3 Processed Bucket**.
  - Callback gửi về Step Functions **chỉ được chứa metadata và tóm tắt nhỏ**.

### 1.2. Chuẩn phân vùng S3 Data Lake (Hive-Style Partitioning)
- TV3 lưu file JSON kết quả đầy đủ trên S3 theo cấu trúc Hive Partitioning đã thống nhất:
  ```
  s3://<processed-bucket>/user_id=<user_id>/year=<YYYY>/month=<MM>/<document_id>.json
  ```
- Chuẩn này giúp tối ưu hóa chi phí truy vấn phân tán khi chạy AWS Athena và EMR.

---

## 2. GIAO DIỆN BẢNG PHỤ `JobCallbacks`

Bảng `JobCallbacks` do TV4 tạo ra (`infra/modules/tv4/dynamodb.tf`) để lưu ánh xạ bất đồng bộ khi Textract xử lý nhiều trang tài liệu.

### Cấu trúc Schema:
| Tên thuộc tính | Kiểu dữ liệu | Ý nghĩa |
|---|---|---|
| **`job_id`** (PK) | String | Khóa chính duy nhất đại diện cho Textract Job (dạng `job-<uuid>`). |
| `task_token` | String | Token tạm dừng do Step Functions cấp (`$$.Task.Token`). |
| `document_id` | String | Mã định danh tài liệu. |
| `user_id` | String | Mã định danh người dùng. |
| `ttl` | Number | Thời điểm hết hạn (Unix timestamp sau 7 ngày). DynamoDB tự động dọn rác miễn phí. |

---

## 3. GIAO DIỆN ĐẦU VÀO VÀ CALLBACK CỦA LAMBDA `StartJob` (TV3)

### 3.1. Input Step Functions truyền cho `StartJob`:
```json
{
  "document_id": "11111111-2222-3333-4444-555555555555",
  "user_id": "test-user-1",
  "document_type": "INVOICE",
  "bucket": "idp-upload-dev",
  "key": "uploads/test-user-1/11111111-2222-3333-4444-555555555555/hoa_don.pdf",
  "attempt": 1,
  "task_token": "AAAAKgAAAAIAAAAAAAAAA..."
}
```

### 3.2. Yêu cầu tính Bất biến (Idempotent) của `StartJob`:
- Khi Step Functions retry (do lỗi mạng hoặc timeout), `StartJob` có thể được gọi lại với cùng `(document_id, attempt)`.
- Lambda `StartJob` nên kiểm tra xem đã có job đang chạy cho document này chưa trước khi gọi lệnh `textract.start_*` mới để tránh tốn chi phí và tránh tạo 2 Textract job song song.
- Lưu nguyên tử `job_id` và `task_token` vào bảng `JobCallbacks`.

### 3.3. Payload Callback TV3 gửi qua `sfn.send_task_success`:
Khi Textract hoàn tất (nhận tín hiệu qua SNS Topic $\rightarrow$ Lambda Parser):
```json
{
  "status": "SUCCEEDED",
  "s3_result_key": "user_id=test-user-1/year=2026/month=11/11111111-2222-3333-4444-555555555555.json",
  "confidence": 96.5,
  "extracted": {
    "vendor": "Công ty Cổ phần Sữa Việt Nam",
    "total_amount": "15,400,000 VND"
  },
  "warnings": []
}
```
*Ghi chú*:
- Nếu tài liệu bị mờ, thiếu trường quan trọng: TV3 trả `status: "NEEDS_REVIEW"` kèm danh sách mã cảnh báo trong mảng `warnings`.
- Trường `extracted`: TV4 hỗ trợ cả kiểu `dict` lẫn chuỗi `JSON string` (tự động `json.loads`).
- Nếu Textract lỗi: TV3 có thể gọi `sfn.send_task_failure(taskToken=..., error=..., cause=...)` hoặc gọi `sfn.send_task_success` kèm `status: "FAILED"`. Cả hai nhánh đều được State Machine bắt và xử lý an toàn.
