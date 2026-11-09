locals {
  native_alarms = {
    processing_dlq = {
      namespace  = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible",
      dimensions = { QueueName = aws_sqs_queue.processing_dlq.name }, threshold = 1, statistic = "Maximum"
    }
    validate_failures = {
      namespace  = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible",
      dimensions = { QueueName = aws_sqs_queue.validate_failures.name }, threshold = 1, statistic = "Maximum"
    }
    queue_age = {
      namespace  = "AWS/SQS", metric = "ApproximateAgeOfOldestMessage",
      dimensions = { QueueName = aws_sqs_queue.processing.name }, threshold = 300, statistic = "Maximum"
    }
    validate_errors = {
      namespace  = "AWS/Lambda", metric = "Errors",
      dimensions = { FunctionName = aws_lambda_function.validate.function_name }, threshold = 1, statistic = "Sum"
    }
    validate_throttles = {
      namespace  = "AWS/Lambda", metric = "Throttles",
      dimensions = { FunctionName = aws_lambda_function.validate.function_name }, threshold = 1, statistic = "Sum"
    }
    validate_dropped = {
      namespace  = "AWS/Lambda", metric = "AsyncEventsDropped",
      dimensions = { FunctionName = aws_lambda_function.validate.function_name }, threshold = 1, statistic = "Sum"
    }
    destination_delivery_failure = {
      namespace  = "AWS/Lambda", metric = "DestinationDeliveryFailures",
      dimensions = { FunctionName = aws_lambda_function.validate.function_name }, threshold = 1, statistic = "Sum"
    }
    workflow_failed = {
      namespace  = "AWS/States", metric = "ExecutionsFailed",
      dimensions = { StateMachineArn = local.state_machine_base_arn }, threshold = 1, statistic = "Sum"
    }
    workflow_timeout = {
      namespace  = "AWS/States", metric = "ExecutionsTimedOut",
      dimensions = { StateMachineArn = local.state_machine_base_arn }, threshold = 1, statistic = "Sum"
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "native" {
  for_each           = local.native_alarms
  alarm_name         = "${var.name_prefix}-${each.key}"
  namespace          = each.value.namespace
  metric_name        = each.value.metric
  dimensions         = each.value.dimensions
  statistic          = each.value.statistic
  period             = 60
  evaluation_periods = 2
  # Alert on isolated errors; require sustained backlog for queue_age.
  datapoints_to_alarm = each.key == "queue_age" ? 2 : 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  tags                = var.tags
}
resource "aws_cloudwatch_metric_alarm" "record_errors" {
  for_each            = toset(["StarterRecordFailed", "InvalidKey", "MissingDocumentRecord", "UploadKeyMismatch"])
  alarm_name          = "${var.name_prefix}-${each.value}"
  namespace           = "IDP/Ingestion"
  metric_name         = each.value
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  tags                = var.tags
}
resource "aws_cloudwatch_metric_alarm" "pending_retries" {
  alarm_name          = "${var.name_prefix}-pending-retries"
  namespace           = "IDP/Ingestion"
  metric_name         = "StarterRecordRetry"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  tags                = var.tags
}
