output "config" {
  value = {
    region                      = var.region
    expected_account_id         = local.account_id
    upload_bucket               = var.upload_bucket_name
    documents_table             = var.documents_table_name
    processing_queue_url        = aws_sqs_queue.processing.url
    processing_dlq_url          = aws_sqs_queue.processing_dlq.url
    validate_failures_queue_url = aws_sqs_queue.validate_failures.url
    state_machine_arn           = var.state_machine_arn
    validate_function_name      = aws_lambda_function.validate.function_name
    starter_function_name       = aws_lambda_function.starter.function_name
  }
}
output "notifications_enabled" { value = var.manage_bucket_notification }
output "processing_enabled" { value = var.enable_processing }
output "alarm_notifications_enabled" { value = length(var.alarm_actions) > 0 }
