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

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags."
}
