terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
provider "aws" {
  region              = var.region
  profile             = var.aws_profile
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = var.project, Environment = "dev", Owner = "TV2" }
  }
}
locals {
  prefix = "${var.project}-tv2-dev"
}
resource "aws_s3_bucket" "upload" {
  bucket        = "${local.prefix}-${var.expected_account_id}-${var.region}"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "upload" {
  bucket                  = aws_s3_bucket.upload.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "upload" {
  bucket = aws_s3_bucket.upload.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_dynamodb_table" "documents" {
  name         = "${local.prefix}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"
  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
}
# A dev acceptance stub; no OCR, callbacks or TV4 status transitions.
resource "aws_sfn_state_machine" "mock" {
  count    = var.create_mock_workflow ? 1 : 0
  name     = "${local.prefix}-mock"
  role_arn = var.workflow_role_arn
  type     = "STANDARD"
  definition = jsonencode({
    Comment = "TV2 dev-only ingestion test; TV4 replaces this workflow."
    StartAt = "AcceptInput"
    States  = { AcceptInput = { Type = "Pass", End = true } }
  })
}
module "tv2" {
  source                     = "../modules/tv2"
  name_prefix                = local.prefix
  region                     = var.region
  upload_bucket_name         = aws_s3_bucket.upload.id
  documents_table_name       = aws_dynamodb_table.documents.name
  lambda_role_arn            = var.lambda_role_arn
  state_machine_arn          = var.create_mock_workflow ? aws_sfn_state_machine.mock[0].arn : var.existing_state_machine_arn
  artifact_directory         = abspath("${path.module}/../../build/tv2")
  manage_bucket_notification = true # this root creates a dedicated, new bucket
  manage_iam_policies        = var.manage_iam_policies
  enable_processing          = var.enable_processing
  alarm_actions              = var.alarm_actions
  tags                       = { Project = var.project, Environment = "dev", Owner = "TV2" }
  depends_on                 = [aws_s3_bucket_public_access_block.upload]
}
output "tv2_config" { value = module.tv2.config }
output "alarm_notifications_enabled" { value = module.tv2.alarm_notifications_enabled }
