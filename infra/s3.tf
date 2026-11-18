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

# 3. Kích hoạt Lambda Validate khi có file mới trong thư mục uploads/
#
# Cố ý chỉ lọc theo prefix, không lọc theo đuôi file: file sai định dạng vẫn
# phải đi vào Validate để được ghi REJECTED kèm lý do. Nếu lọc theo đuôi file,
# các file đó sẽ nằm mãi ở UPLOAD_PENDING và người dùng không thấy phản hồi.
resource "aws_lambda_permission" "s3_invoke_validate" {
  statement_id  = "AllowS3InvokeValidate"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.validate.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.upload.arn
}

resource "aws_s3_bucket_notification" "upload" {
  bucket = aws_s3_bucket.upload.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.validate.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
  }

  depends_on = [aws_lambda_permission.s3_invoke_validate]
}
