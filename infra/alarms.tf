################################################################################
# OBSERVABILITY & MONITORING LAYER (CLOUDWATCH ALARMS)
#
# Hệ thống cảnh báo tự động cho pipeline:
# 1. Cảnh báo khi có file/message rơi vào Dead Letter Queue (DLQ)
# 2. Cảnh báo khi Lambda Validate hoặc Parse xảy ra lỗi runtime
# 3. Cảnh báo khi Step Functions State Machine thực thi thất bại
################################################################################

# SNS Topic nhận thông báo cảnh báo khẩn cấp cho đội ngũ DevOps
resource "aws_sns_topic" "devops_alerts" {
  name = "${local.name_prefix}-devops-cloudwatch-alerts"
}

# 1. Cảnh báo Dead Letter Queue: Báo động ngay khi có bất kỳ message lỗi nào rơi vào DLQ
resource "aws_cloudwatch_metric_alarm" "dlq_messages_visible" {
  alarm_name          = "${local.name_prefix}-dlq-has-failed-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Canh bao: Co it nhat 1 message bi loi da roi vao Dead Letter Queue can kiem tra!"
  alarm_actions       = [aws_sns_topic.devops_alerts.arn]

  dimensions = {
    QueueName = aws_sqs_queue.ingestion_dlq.name
  }
}

# 2. Cảnh báo lỗi runtime của Lambda Validate
resource "aws_cloudwatch_metric_alarm" "lambda_validate_errors" {
  alarm_name          = "${local.name_prefix}-lambda-validate-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Canh bao: Lambda Validate gap loi runtime khi xu ly file upload!"
  alarm_actions       = [aws_sns_topic.devops_alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.validate.function_name
  }
}

# 3. Cảnh báo lỗi runtime của Lambda Parse
resource "aws_cloudwatch_metric_alarm" "lambda_parse_errors" {
  alarm_name          = "${local.name_prefix}-lambda-parse-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Canh bao: Lambda Parse gap loi khi boc tach du lieu JSON Textract!"
  alarm_actions       = [aws_sns_topic.devops_alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.parse.function_name
  }
}

# 4. Cảnh báo khi Step Functions State Machine thực thi thất bại
resource "aws_cloudwatch_metric_alarm" "step_functions_failed" {
  alarm_name          = "${local.name_prefix}-step-functions-executions-failed"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Canh bao: Luong dieu phoi Step Functions bi fail!"
  alarm_actions       = [aws_sns_topic.devops_alerts.arn]

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.pipeline.arn
  }
}
