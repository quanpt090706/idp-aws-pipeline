################################################################################
# RUNTIME IAM FOR THE ROOT DEV STACK
#
# AWS Academy thường yêu cầu dùng role có sẵn. Ngoài Academy, Terraform tạo
# role riêng cho Lambda, Step Functions và Textract với trust policy đúng.
################################################################################

resource "aws_iam_role" "workflow" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-workflow-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role" "textract_publish" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-textract-sns-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "textract.amazonaws.com" }
    }]
  })
}

locals {
  workflow_role_arn = var.workflow_role_arn != "" ? var.workflow_role_arn : (
    var.use_lab_role ? local.lambda_role_arn : aws_iam_role.workflow[0].arn
  )
  textract_role_arn = var.textract_role_arn != "" ? var.textract_role_arn : (
    var.use_lab_role ? local.lambda_role_arn : aws_iam_role.textract_publish[0].arn
  )
}

resource "aws_iam_role_policy" "textract_publish" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-textract-publish-sns"
  role  = aws_iam_role.textract_publish[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sns:Publish"
      Resource = aws_sns_topic.textract_complete.arn
    }]
  })
}

# Root stack hiện dùng chung một execution role cho các Lambda backend. Policy
# này chỉ được tạo ngoài Academy; với Academy, TV5 phải xác minh LabRole có các
# quyền tương đương trước khi apply.
resource "aws_iam_role_policy" "lambda_pipeline" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-lambda-pipeline"
  role  = aws_iam_role.lambda_exec[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "textract:StartExpenseAnalysis",
          "textract:StartDocumentAnalysis",
          "textract:GetExpenseAnalysis",
          "textract:GetDocumentAnalysis"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = [
          aws_dynamodb_table.documents.arn,
          aws_dynamodb_table.job_callbacks.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.upload.arn}/uploads/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.results.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.processing.arn,
          aws_sqs_queue.ingestion_dlq.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution",
          "states:DescribeExecution"
        ]
        Resource = "${replace(aws_sfn_state_machine.pipeline.arn, ":stateMachine:", ":execution:")}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = local.textract_role_arn
        Condition = {
          StringEquals = { "iam:PassedToService" = "textract.amazonaws.com" }
        }
      },
      {
        Effect   = "Allow"
        Action   = "ses:SendEmail"
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "workflow" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-workflow"
  role  = aws_iam_role.workflow[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.documents.arn
      },
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [
          aws_lambda_function.start_job.arn,
          aws_lambda_function.notification.arn
        ]
      }
    ]
  })
}
