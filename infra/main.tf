locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# Tạo chuỗi ngẫu nhiên 6 ký tự viết thường để tên S3 Bucket không bị trùng lặp trên toàn cầu
resource "random_string" "bucket_suffix" {
  length  = 6
  special = false
  upper   = false
}
