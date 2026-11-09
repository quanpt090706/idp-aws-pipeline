################################################################################
# STORAGE LAYER (S3 BUCKETS)
#
# Quản lý 2 S3 Bucket chính:
# 1. Upload Bucket: Nhận file tài liệu gốc từ người dùng
# 2. Results Bucket: Lưu trữ kết quả JSON thô trích xuất từ Amazon Textract
################################################################################

# 1. S3 Upload Bucket
resource "aws_s3_bucket" "upload" {
  bucket        = "${local.name_prefix}-upload-${random_string.bucket_suffix.result}"
  force_destroy = true # Hỗ trợ dev: Cho phép xóa bucket khi còn file test bên trong
}

# Chặn hoàn toàn truy cập công khai (Public Access)
resource "aws_s3_bucket_public_access_block" "upload" {
  bucket                  = aws_s3_bucket.upload.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Mã hóa dữ liệu lưu trữ phía máy chủ (SSE-S3 AES256)
resource "aws_s3_bucket_server_side_encryption_configuration" "upload" {
  bucket = aws_s3_bucket.upload.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 2. S3 Results Bucket
resource "aws_s3_bucket" "results" {
  bucket        = "${local.name_prefix}-results-${random_string.bucket_suffix.result}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket                  = aws_s3_bucket.results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
