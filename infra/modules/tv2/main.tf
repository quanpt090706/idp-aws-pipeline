data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id              = data.aws_caller_identity.current.account_id
  partition               = data.aws_partition.current.partition
  table_arn               = "arn:${local.partition}:dynamodb:${var.region}:${local.account_id}:table/${var.documents_table_name}"
  bucket_arn              = "arn:${local.partition}:s3:::${var.upload_bucket_name}"
  execution_arn           = "arn:${local.partition}:states:${var.region}:${local.account_id}:execution:${split(":", var.state_machine_arn)[6]}:*"
  role_name               = element(reverse(split("/", var.lambda_role_arn)), 0)
  state_machine_base_arn  = join(":", slice(split(":", var.state_machine_arn), 0, 7))
  state_machine_qualifier = try(split(":", var.state_machine_arn)[7], null)
}

resource "aws_sqs_queue" "processing_dlq" {
  name                      = "${var.name_prefix}-processing-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}
resource "aws_sqs_queue" "processing" {
  name                       = "${var.name_prefix}-processing"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = 5
  })
  tags = var.tags
}
resource "aws_sqs_queue_redrive_allow_policy" "processing" {
  queue_url = aws_sqs_queue.processing_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.processing.arn]
  })
}
resource "aws_sqs_queue" "validate_failures" {
  name                      = "${var.name_prefix}-validate-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}

# Optional: Academy often denies IAM role/policy mutation.
resource "aws_iam_role_policy" "tv2" {
  count = var.manage_iam_policies ? 1 : 0
  name  = "${var.name_prefix}-ingestion"
  role  = local.role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.bucket_arn}/uploads/*"] },
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:UpdateItem"], Resource = [local.table_arn] },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [aws_sqs_queue.processing.arn, aws_sqs_queue.validate_failures.arn] },
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = [aws_sqs_queue.processing.arn] },
      merge(
        { Effect = "Allow", Action = ["states:StartExecution"], Resource = [local.state_machine_base_arn] },
        local.state_machine_qualifier == null ? {} : {
          Condition = {
            "ForAnyValue:StringEquals" = {
              "states:StateMachineQualifier" = [local.state_machine_qualifier]
            }
          }
        }
      ),
      { Effect = "Allow", Action = ["states:DescribeExecution"], Resource = [local.execution_arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = [
        "${aws_cloudwatch_log_group.validate.arn}:*",
        "${aws_cloudwatch_log_group.starter.arn}:*"
      ] }
    ]
  })
}
resource "aws_cloudwatch_log_group" "validate" {
  name              = "/aws/lambda/${var.name_prefix}-validate"
  retention_in_days = 14
  tags              = var.tags
}
resource "aws_cloudwatch_log_group" "starter" {
  name              = "/aws/lambda/${var.name_prefix}-workflow-starter"
  retention_in_days = 14
  tags              = var.tags
}
resource "aws_lambda_function" "validate" {
  function_name    = "${var.name_prefix}-validate"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.lambda_handler"
  filename         = "${var.artifact_directory}/validate.zip"
  source_code_hash = filebase64sha256("${var.artifact_directory}/validate.zip")
  timeout          = 30
  memory_size      = 256
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.validate.name
  }
  environment {
    variables = {
      DOCUMENTS_TABLE     = var.documents_table_name
      QUEUE_URL           = aws_sqs_queue.processing.url
      UPLOAD_BUCKET       = var.upload_bucket_name
      UPLOAD_PREFIX       = "uploads/"
      MAX_FILE_SIZE_BYTES = "10485760"
    }
  }
  depends_on = [aws_iam_role_policy.tv2]
  tags       = var.tags
}
resource "aws_lambda_function" "starter" {
  function_name    = "${var.name_prefix}-workflow-starter"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "app.lambda_handler"
  filename         = "${var.artifact_directory}/workflow-starter.zip"
  source_code_hash = filebase64sha256("${var.artifact_directory}/workflow-starter.zip")
  timeout          = 30
  memory_size      = 128
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.starter.name
  }
  environment {
    variables = {
      DOCUMENTS_TABLE   = var.documents_table_name
      UPLOAD_BUCKET     = var.upload_bucket_name
      UPLOAD_PREFIX     = "uploads/"
      STATE_MACHINE_ARN = var.state_machine_arn
    }
  }
  depends_on = [aws_iam_role_policy.tv2]
  tags       = var.tags
}
resource "aws_lambda_permission" "s3" {
  statement_id   = "AllowUploadBucket"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.validate.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = local.bucket_arn
  source_account = local.account_id
}
resource "aws_s3_bucket_notification" "upload" {
  count  = var.manage_bucket_notification ? 1 : 0
  bucket = var.upload_bucket_name
  lambda_function {
    lambda_function_arn = aws_lambda_function.validate.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
  }
  depends_on = [aws_lambda_permission.s3]
}
resource "aws_lambda_function_event_invoke_config" "validate" {
  function_name                = aws_lambda_function.validate.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600
  destination_config {
    on_failure {
      destination = aws_sqs_queue.validate_failures.arn
    }
  }
}
resource "aws_lambda_event_source_mapping" "starter" {
  event_source_arn                   = aws_sqs_queue.processing.arn
  function_name                      = aws_lambda_function.starter.arn
  enabled                            = var.enable_processing
  batch_size                         = 5
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 5
  }
}
