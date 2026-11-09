################################################################################
# INGESTION & QUEUE LAYER (SQS + DEAD LETTER QUEUE)
#
# Đóng vai trò là bộ đệm chịu tải (Shock Absorber):
# - Nhận thông báo upload từ S3 Event
# - Đệm tải chống throttle cho Lambda và Textract
# - Cách ly tin nhắn lỗi vào DLQ sau 3 lần retry thất bại
################################################################################

# 1. Dead Letter Queue (DLQ) cho ingestion
resource "aws_sqs_queue" "ingestion_dlq" {
  name                      = "${local.name_prefix}-ingestion-dlq"
  message_retention_seconds = 1209600 # 14 ngày (tối đa để kịp điều tra & redrive lỗi)
  sqs_managed_sse_enabled   = true
}

# 2. Hàng đợi xử lý chính (Processing Queue)
resource "aws_sqs_queue" "processing" {
  name                       = "${local.name_prefix}-processing-queue"
  visibility_timeout_seconds = 180    # 3 phút (đủ thời gian cho Lambda validate/starter xử lý)
  message_retention_seconds  = 345600 # 4 ngày
  receive_wait_time_seconds  = 20     # Long polling 20s (tiết kiệm chi phí request)
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingestion_dlq.arn
    maxReceiveCount     = 3 # Thử lại tối đa 3 lần trước khi đẩy vào DLQ
  })
}

# Cấu hình chính sách cho phép DLQ nhận tin nhắn từ Processing Queue
resource "aws_sqs_queue_redrive_allow_policy" "processing_dlq" {
  queue_url = aws_sqs_queue.ingestion_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.processing.arn]
  })
}
