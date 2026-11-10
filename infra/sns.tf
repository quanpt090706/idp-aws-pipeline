################################################################################
# NOTIFICATION LAYER (SNS TOPIC)
#
# Nhận tín hiệu callback bất đồng bộ từ Amazon Textract khi hoàn tất OCR
################################################################################

resource "aws_sns_topic" "textract_complete" {
  name = "${local.name_prefix}-textract-job-complete"
}

# Cho SNS gọi Lambda Parse khi Textract gửi thông báo hoàn tất.
resource "aws_lambda_permission" "sns_invoke_parse" {
  statement_id  = "AllowTextractCompletionSns"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.parse.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.textract_complete.arn
}

resource "aws_sns_topic_subscription" "textract_parse" {
  topic_arn = aws_sns_topic.textract_complete.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.parse.arn

  depends_on = [aws_lambda_permission.sns_invoke_parse]
}
