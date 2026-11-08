################################################################################
# NOTIFICATION LAYER (SNS TOPIC)
#
# Nhận tín hiệu callback bất đồng bộ từ Amazon Textract khi hoàn tất OCR
################################################################################

resource "aws_sns_topic" "textract_complete" {
  name = "${local.name_prefix}-textract-job-complete"
}
