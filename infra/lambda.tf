################################################################################
# COMPUTE LAYER (LAMBDA)
#
# Quản lý các Lambda Function chính của pipeline:
# 1. Validate: Kiểm tra định dạng & dung lượng file upload (TV2)
# 2. Workflow Starter: Nhận SQS và khởi động Step Functions (TV2)
# 3. Start-Job: Kích hoạt Amazon Textract Async (TV3)
# 4. Parse: Xử lý và trích xuất JSON Textract (TV3)
# 5. Notification: Gửi email kết quả (TV4)
################################################################################

# 1. Đóng gói mã nguồn từng Lambda thành file ZIP tự động
data "archive_file" "validate_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/validate"
  output_path = "${path.module}/build/validate.zip"
}

data "archive_file" "start_job_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/start-job"
  output_path = "${path.module}/build/start_job.zip"
}

data "archive_file" "parse_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/parse"
  output_path = "${path.module}/build/parse.zip"
}

data "archive_file" "workflow_starter_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/workflow-starter"
  output_path = "${path.module}/build/workflow_starter.zip"
}

data "archive_file" "notification_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/notification"
  output_path = "${path.module}/build/notification.zip"
}

# 2. IAM Role cho Lambda (tự tạo nếu không dùng LabRole của trường)
resource "aws_iam_role" "lambda_exec" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.lambda_exec[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

locals {
  # AWS cá nhân: Terraform tự tạo role. AWS Academy: dùng LabRole có sẵn.
  lambda_role_arn = var.use_lab_role ? var.lab_role_arn : one(aws_iam_role.lambda_exec[*].arn)
}

check "lab_role_configured" {
  assert {
    condition     = !var.use_lab_role || var.lab_role_arn != ""
    error_message = "use_lab_role = true yêu cầu lab_role_arn. Với tài khoản AWS cá nhân, đặt use_lab_role = false."
  }
}

# 3. Lambda Validate Function
resource "aws_lambda_function" "validate" {
  function_name    = "${local.name_prefix}-validate"
  filename         = data.archive_file.validate_zip.output_path
  source_code_hash = data.archive_file.validate_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = local.lambda_role_arn
  timeout          = 30

  environment {
    variables = {
      DOCUMENTS_TABLE     = aws_dynamodb_table.documents.name
      QUEUE_URL           = aws_sqs_queue.processing.url
      UPLOAD_BUCKET       = aws_s3_bucket.upload.id
      UPLOAD_PREFIX       = "uploads/"
      MAX_FILE_SIZE_BYTES = "10485760"
    }
  }
}

# 4. Lambda Workflow Starter (TV2): nhận message từ SQS và khởi động Step Functions
resource "aws_lambda_function" "workflow_starter" {
  function_name    = "${local.name_prefix}-workflow-starter"
  filename         = data.archive_file.workflow_starter_zip.output_path
  source_code_hash = data.archive_file.workflow_starter_zip.output_base64sha256
  handler          = "app.lambda_handler"
  runtime          = "python3.12"
  role             = local.lambda_role_arn
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      DOCUMENTS_TABLE   = aws_dynamodb_table.documents.name
      STATE_MACHINE_ARN = aws_sfn_state_machine.pipeline.arn
      UPLOAD_BUCKET     = aws_s3_bucket.upload.id
      UPLOAD_PREFIX     = "uploads/"
    }
  }
}

# 4. Lambda Start-Job Function
resource "aws_lambda_function" "start_job" {
  function_name    = "${local.name_prefix}-start-job"
  filename         = data.archive_file.start_job_zip.output_path
  source_code_hash = data.archive_file.start_job_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = local.lambda_role_arn
  timeout          = 60

  environment {
    variables = {
      SNS_TOPIC_ARN       = aws_sns_topic.textract_complete.arn
      TEXTRACT_ROLE_ARN   = local.textract_role_arn
      JOB_CALLBACKS_TABLE = aws_dynamodb_table.job_callbacks.name
    }
  }
}

# 5. Lambda Parse Function
resource "aws_lambda_function" "parse" {
  function_name    = "${local.name_prefix}-parse"
  filename         = data.archive_file.parse_zip.output_path
  source_code_hash = data.archive_file.parse_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = local.lambda_role_arn
  timeout          = 180
  memory_size      = 256 # Parse JSON Textract lớn cần thêm bộ nhớ

  environment {
    variables = {
      JOB_CALLBACKS_TABLE  = aws_dynamodb_table.job_callbacks.name
      S3_RESULTS_BUCKET    = aws_s3_bucket.results.id
      CONFIDENCE_THRESHOLD = tostring(var.confidence_threshold)
    }
  }
}

# 6. Lambda Notification Function (TV4). State machine gọi Lambda này sau khi
# TV3 callback thành công/thất bại; không được trỏ nhầm về StartJob.
resource "aws_lambda_function" "notification" {
  function_name    = "${local.name_prefix}-notification"
  filename         = data.archive_file.notification_zip.output_path
  source_code_hash = data.archive_file.notification_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = local.lambda_role_arn
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      DOCUMENTS_TABLE         = aws_dynamodb_table.documents.name
      SENDER_EMAIL            = var.notification_email
      DEMO_NOTIFICATION_EMAIL = var.notification_email
    }
  }
}
