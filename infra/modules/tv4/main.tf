locals {
  documents_table_name = var.create_dynamodb_tables ? aws_dynamodb_table.documents[0].name : var.existing_documents_table_name
  notification_lambda_arn = var.notification_lambda_arn != "" ? var.notification_lambda_arn : (
    var.create_notification_lambda ? aws_lambda_function.notification[0].arn : ""
  )
}

data "archive_file" "notification" {
  count       = var.create_notification_lambda && var.notification_lambda_arn == "" ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/../../../lambdas/notification"
  output_path = "${path.module}/../../build/notification.zip"
}

resource "aws_cloudwatch_log_group" "notification" {
  count             = var.create_notification_lambda && var.notification_lambda_arn == "" ? 1 : 0
  name              = "/aws/lambda/${var.name_prefix}-notification"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_lambda_function" "notification" {
  count            = var.create_notification_lambda && var.notification_lambda_arn == "" ? 1 : 0
  function_name    = "${var.name_prefix}-notification"
  role             = var.lambda_role_arn != "" ? var.lambda_role_arn : var.workflow_role_arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.notification[0].output_path
  source_code_hash = data.archive_file.notification[0].output_base64sha256
  timeout          = 30
  memory_size      = 256
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.notification[0].name
  }
  environment {
    variables = {
      DOCUMENTS_TABLE         = local.documents_table_name
      SENDER_EMAIL            = var.sender_email
      DEMO_NOTIFICATION_EMAIL = var.demo_notification_email
      AWS_REGION              = var.region
    }
  }
  tags = var.tags
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.name_prefix}-pipeline"
  role_arn = var.workflow_role_arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/../../step_functions/state_machine.asl.json", {
    DOCUMENTS_TABLE_NAME    = local.documents_table_name
    START_JOB_LAMBDA_ARN    = var.start_job_lambda_arn
    NOTIFICATION_LAMBDA_ARN = local.notification_lambda_arn
  })

  tags = var.tags
}
