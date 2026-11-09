variable "name_prefix" {
  type        = string
  description = "Prefix dùng để đặt tên các tài nguyên AWS."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,39}$", var.name_prefix))
    error_message = "Prefix phải gồm 2-40 ký tự chữ thường, số hoặc dấu gạch ngang."
  }
}

variable "region" {
  type        = string
  description = "AWS region triển khai."
}

variable "workflow_role_arn" {
  type        = string
  description = "IAM Role ARN dùng cho Step Functions State Machine (phải trust states.amazonaws.com)."
}

variable "start_job_lambda_arn" {
  type        = string
  description = "Lambda ARN của StartJob (TV3) để gọi khởi tạo Textract với TaskToken."
}

variable "notification_lambda_arn" {
  type        = string
  default     = ""
  description = "Lambda ARN của Notification (SES) để Step Functions gọi gửi thông báo. Nếu để trống và create_notification_lambda = true, module sẽ tự tạo Lambda."
}

variable "create_notification_lambda" {
  type        = bool
  default     = true
  description = "Tự động đóng gói và tạo Lambda Notification nếu chưa có notification_lambda_arn."
}

variable "lambda_role_arn" {
  type        = string
  default     = ""
  description = "IAM Role ARN dùng cho Lambda Notification (nếu để trống sẽ dùng var.workflow_role_arn)."
}

variable "sender_email" {
  type        = string
  default     = "noreply@idp-pipeline.aws"
  description = "Email gửi thông báo SES (phải là verified identity trong SES)."
}

variable "demo_notification_email" {
  type        = string
  default     = ""
  description = "Email nhận cố định cho môi trường SES Sandbox (nếu để trống sẽ lấy từ DynamoDB hoặc sender_email)."
}

variable "create_dynamodb_tables" {
  type        = bool
  default     = true
  description = "Tự động tạo bảng Documents và JobCallbacks nếu chưa có sẵn."
}

variable "existing_documents_table_name" {
  type        = string
  default     = ""
  description = "Tên bảng Documents nếu sử dụng bảng có sẵn do TV5 tạo."
}

variable "manage_iam_policies" {
  type        = bool
  default     = false
  description = "Quản lý IAM inline policy (mặc định false cho môi trường AWS Academy LabRole để tránh lỗi AccessDenied)."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags."
}
