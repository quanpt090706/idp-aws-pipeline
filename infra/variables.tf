################################################################################
# 1. Biến môi trường và vùng triển khai
################################################################################

variable "aws_region" {
  description = "AWS Region dùng cho dự án (khuyến nghị us-east-1 cho tài khoản cá nhân)"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Tên định danh dự án, dùng làm tiền tố (prefix) cho toàn bộ tài nguyên"
  type        = string
  default     = "idp"
}

variable "environment" {
  description = "Môi trường triển khai (dev / staging / prod)"
  type        = string
  default     = "dev"
}

################################################################################
# 2. Cấu hình AWS Academy Learner Lab vs tài khoản AWS cá nhân
################################################################################

variable "use_lab_role" {
  description = "Chỉ bật true khi dùng AWS Academy Learner Lab và muốn tái sử dụng LabRole. Tài khoản cá nhân để false để Terraform tự tạo IAM Role."
  type        = bool
  default     = false
}

variable "lab_role_arn" {
  description = "ARN của LabRole trong AWS Academy (chỉ dùng khi use_lab_role = true)."
  type        = string
  default     = ""
}

variable "workflow_role_arn" {
  description = "ARN role có trust states.amazonaws.com. Để trống sẽ dùng LabRole ở Academy hoặc role do Terraform tạo ngoài Academy."
  type        = string
  default     = ""
}

variable "textract_role_arn" {
  description = "ARN role có trust textract.amazonaws.com và quyền publish SNS. Để trống sẽ dùng LabRole ở Academy hoặc role do Terraform tạo ngoài Academy."
  type        = string
  default     = ""
}

variable "confidence_threshold" {
  description = "Ngưỡng confidence để TV3 gắn NEEDS_REVIEW."
  type        = number
  default     = 80

  validation {
    condition     = var.confidence_threshold >= 0 && var.confidence_threshold <= 100
    error_message = "confidence_threshold phải nằm trong khoảng 0 đến 100."
  }
}

################################################################################
# 3. Cấu hình vận hành và giám sát (DevOps)
################################################################################

variable "log_retention_days" {
  description = "Số ngày lưu log CloudWatch (đặt 7 ngày để tối ưu chi phí)"
  type        = number
  default     = 7
}
