output "state_machine_arn" {
  description = "ARN của Step Functions State Machine."
  value       = aws_sfn_state_machine.pipeline.arn
}

output "state_machine_name" {
  description = "Tên của Step Functions State Machine."
  value       = aws_sfn_state_machine.pipeline.name
}

output "documents_table_name" {
  description = "Tên bảng DynamoDB Documents."
  value       = local.documents_table_name
}

output "documents_table_arn" {
  description = "ARN bảng DynamoDB Documents."
  value       = var.create_dynamodb_tables ? aws_dynamodb_table.documents[0].arn : ""
}

output "job_callbacks_table_name" {
  description = "Tên bảng DynamoDB JobCallbacks."
  value       = var.create_dynamodb_tables ? aws_dynamodb_table.job_callbacks[0].name : ""
}

output "job_callbacks_table_arn" {
  description = "ARN bảng DynamoDB JobCallbacks."
  value       = var.create_dynamodb_tables ? aws_dynamodb_table.job_callbacks[0].arn : ""
}

output "notification_lambda_arn" {
  description = "ARN của Lambda gửi thông báo qua SES."
  value       = local.notification_lambda_arn
}

output "notification_lambda_name" {
  description = "Tên Lambda gửi thông báo qua SES."
  value       = var.create_notification_lambda && var.notification_lambda_arn == "" ? aws_lambda_function.notification[0].function_name : ""
}
