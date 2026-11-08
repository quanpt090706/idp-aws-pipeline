################################################################################
# THÔNG TIN ĐẦU RA (OUTPUTS BÀN GIAO CHO NHÓM)
#
# Cung cấp chính xác ARN, Name, URL của các tài nguyên AWS đã tạo
# để TV1, TV2, TV3, TV4 cấu hình code local và kết nối hệ thống.
################################################################################

output "aws_region" {
  description = "Region mà toàn bộ hệ thống đang hoạt động"
  value       = var.aws_region
}

output "project_prefix" {
  description = "Tiền tố đặt tên chuẩn cho toàn dự án"
  value       = local.name_prefix
}

# --- 1. Storage (S3) ---
output "s3_upload_bucket_name" {
  description = "Tên S3 Upload Bucket"
  value       = aws_s3_bucket.upload.id
}

output "s3_upload_bucket_arn" {
  description = "ARN của S3 Upload Bucket"
  value       = aws_s3_bucket.upload.arn
}

output "s3_results_bucket_name" {
  description = "Tên S3 Results Bucket (lưu raw JSON Textract)"
  value       = aws_s3_bucket.results.id
}

output "s3_results_bucket_arn" {
  description = "ARN của S3 Results Bucket"
  value       = aws_s3_bucket.results.arn
}

# --- 2. Ingestion & Queue (SQS) ---
output "sqs_processing_queue_name" {
  description = "Tên hàng đợi xử lý chính"
  value       = aws_sqs_queue.processing.name
}

output "sqs_processing_queue_url" {
  description = "URL hàng đợi xử lý chính"
  value       = aws_sqs_queue.processing.url
}

output "sqs_processing_queue_arn" {
  description = "ARN hàng đợi xử lý chính"
  value       = aws_sqs_queue.processing.arn
}

output "sqs_dlq_name" {
  description = "Tên Dead Letter Queue"
  value       = aws_sqs_queue.ingestion_dlq.name
}

output "sqs_dlq_url" {
  description = "URL Dead Letter Queue"
  value       = aws_sqs_queue.ingestion_dlq.url
}

output "sqs_dlq_arn" {
  description = "ARN Dead Letter Queue"
  value       = aws_sqs_queue.ingestion_dlq.arn
}

# --- 3. Data Layer (DynamoDB) ---
output "dynamodb_documents_table_name" {
  description = "Tên bảng DynamoDB chính lưu tài liệu đã bóc tách"
  value       = aws_dynamodb_table.documents.name
}

output "dynamodb_documents_table_arn" {
  description = "ARN của bảng DynamoDB documents"
  value       = aws_dynamodb_table.documents.arn
}

output "dynamodb_job_callbacks_table_name" {
  description = "Tên bảng DynamoDB quản lý Job Callbacks"
  value       = aws_dynamodb_table.job_callbacks.name
}

output "dynamodb_job_callbacks_table_arn" {
  description = "ARN của bảng DynamoDB job-callbacks"
  value       = aws_dynamodb_table.job_callbacks.arn
}

# --- 4. Notification (SNS) ---
output "sns_textract_topic_name" {
  description = "Tên SNS Topic nhận callback khi Textract hoàn tất"
  value       = aws_sns_topic.textract_complete.name
}

output "sns_textract_topic_arn" {
  description = "ARN của SNS Topic Textract"
  value       = aws_sns_topic.textract_complete.arn
}
