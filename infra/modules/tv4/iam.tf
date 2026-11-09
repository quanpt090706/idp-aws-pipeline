data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  partition    = data.aws_partition.current.partition
  table_arn    = "arn:${local.partition}:dynamodb:${var.region}:${local.account_id}:table/${local.documents_table_name}"
  sfn_role_name = element(reverse(split("/", var.workflow_role_arn)), 0)
  lambda_role_name = element(reverse(split("/", var.lambda_role_arn != "" ? var.lambda_role_arn : var.workflow_role_arn)), 0)
}

# Policy cho Step Functions Orchestrator (chỉ áp dụng khi manage_iam_policies = true)
resource "aws_iam_role_policy" "step_functions" {
  count = var.manage_iam_policies ? 1 : 0
  name  = "${var.name_prefix}-sfn-orchestration"
  role  = local.sfn_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem",
          "dynamodb:GetItem"
        ]
        Resource = [
          local.table_arn,
          "${local.table_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = compact([
          var.start_job_lambda_arn,
          local.notification_lambda_arn
        ])
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# Policy cho Lambda Notification (chỉ áp dụng khi manage_iam_policies = true)
resource "aws_iam_role_policy" "notification" {
  count = var.manage_iam_policies && var.create_notification_lambda && var.notification_lambda_arn == "" ? 1 : 0
  name  = "${var.name_prefix}-notification-ses"
  role  = local.lambda_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = [local.table_arn]
      },
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = [
          "arn:${local.partition}:ses:${var.region}:${local.account_id}:identity/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "${aws_cloudwatch_log_group.notification[0].arn}:*"
        ]
      }
    ]
  })
}
