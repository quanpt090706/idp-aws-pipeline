# Offline plans with a mocked AWS provider; these never provision real resources.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_resource "aws_sfn_state_machine" {
    defaults = { arn = "arn:aws:states:us-east-1:123456789012:stateMachine:tv2-mock" }
  }
  # Resolve policy dependencies so its JSON can be checked without applying.
  mock_resource "aws_sqs_queue" {
    override_during = plan
    defaults        = { arn = "arn:aws:sqs:us-east-1:123456789012:idp-test" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    override_during = plan
    defaults        = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/idp-test" }
  }
}

run "iam_unqualified_workflow" {
  command = plan
  module {
    source = "../modules/tv2"
  }
  variables {
    name_prefix          = "idp-test"
    region               = "us-east-1"
    upload_bucket_name   = "idp-test"
    documents_table_name = "Documents"
    state_machine_arn    = "arn:aws:states:us-east-1:123456789012:stateMachine:tv4-workflow"
    lambda_role_arn      = "arn:aws:iam::123456789012:role/LambdaTestRole"
    artifact_directory   = "../../build/tv2"
    manage_iam_policies  = true
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.tv2[0].policy).Statement[4].Resource == [var.state_machine_arn]
    error_message = "StartExecution must authorize the base state machine ARN."
  }
  assert {
    condition     = !contains(keys(jsondecode(aws_iam_role_policy.tv2[0].policy).Statement[4]), "Condition")
    error_message = "Unqualified workflows must not emit a qualifier condition."
  }
}

run "iam_workflow_alias" {
  command = plan
  module {
    source = "../modules/tv2"
  }
  variables {
    name_prefix          = "idp-test"
    region               = "us-east-1"
    upload_bucket_name   = "idp-test"
    documents_table_name = "Documents"
    state_machine_arn    = "arn:aws:states:us-east-1:123456789012:stateMachine:tv4-workflow:PROD"
    lambda_role_arn      = "arn:aws:iam::123456789012:role/LambdaTestRole"
    artifact_directory   = "../../build/tv2"
    manage_iam_policies  = true
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.tv2[0].policy).Statement[4].Resource == ["arn:aws:states:us-east-1:123456789012:stateMachine:tv4-workflow"]
    error_message = "Alias authorization must use the base state machine ARN."
  }
  assert {
    condition     = try(jsondecode(aws_iam_role_policy.tv2[0].policy).Statement[4].Condition["ForAnyValue:StringEquals"]["states:StateMachineQualifier"] == ["PROD"], false)
    error_message = "Alias authorization must remain restricted to the requested qualifier."
  }
}

run "iam_workflow_version" {
  command = plan
  module {
    source = "../modules/tv2"
  }
  variables {
    name_prefix          = "idp-test"
    region               = "us-east-1"
    upload_bucket_name   = "idp-test"
    documents_table_name = "Documents"
    state_machine_arn    = "arn:aws:states:us-east-1:123456789012:stateMachine:tv4-workflow:3"
    lambda_role_arn      = "arn:aws:iam::123456789012:role/LambdaTestRole"
    artifact_directory   = "../../build/tv2"
    manage_iam_policies  = true
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.tv2[0].policy).Statement[4].Resource == ["arn:aws:states:us-east-1:123456789012:stateMachine:tv4-workflow"]
    error_message = "Version authorization must use the base state machine ARN."
  }
  assert {
    condition     = try(jsondecode(aws_iam_role_policy.tv2[0].policy).Statement[4].Condition["ForAnyValue:StringEquals"]["states:StateMachineQualifier"] == ["3"], false)
    error_message = "Version authorization must remain restricted to the requested qualifier."
  }
}

run "dev_safe_defaults" {
  command = plan
  variables {
    region              = "us-east-1"
    expected_account_id = "123456789012"
    lambda_role_arn     = "arn:aws:iam::123456789012:role/LambdaTestRole"
    workflow_role_arn   = "arn:aws:iam::123456789012:role/WorkflowTestRole"
  }
  assert {
    condition     = aws_sfn_state_machine.mock[0].type == "STANDARD"
    error_message = "The dev workflow must be Standard."
  }
  assert {
    condition     = module.tv2.processing_enabled == false
    error_message = "Processing must remain disabled until the lab is checked."
  }
  assert {
    condition     = aws_s3_bucket.upload.force_destroy == false && aws_s3_bucket_public_access_block.upload.block_public_policy
    error_message = "Do not auto-delete uploads or make the upload bucket public."
  }
}

run "tv2_module_contract" {
  command = plan
  module {
    source = "../modules/tv2"
  }
  override_resource {
    target          = aws_sqs_queue.processing_dlq
    override_during = plan
    values = {
      arn = "arn:aws:sqs:us-east-1:123456789012:idp-test-processing-dlq"
    }
  }
  variables {
    name_prefix          = "idp-test"
    region               = "us-east-1"
    upload_bucket_name   = "idp-test"
    documents_table_name = "Documents"
    state_machine_arn    = "arn:aws:states:us-east-1:123456789012:stateMachine:tv2-mock"
    lambda_role_arn      = "arn:aws:iam::123456789012:role/LambdaTestRole"
    artifact_directory   = "../../build/tv2"
  }
  assert {
    condition     = aws_sqs_queue.processing.visibility_timeout_seconds >= 6 * aws_lambda_function.starter.timeout
    error_message = "SQS visibility must be at least 6 times the consumer timeout."
  }
  assert {
    condition     = jsondecode(aws_sqs_queue.processing.redrive_policy).maxReceiveCount == 5
    error_message = "The processing queue needs maxReceiveCount=5."
  }
  assert {
    condition     = aws_sqs_queue.processing_dlq.message_retention_seconds > aws_sqs_queue.processing.message_retention_seconds
    error_message = "DLQ retention must exceed source retention."
  }
  assert {
    condition     = contains(aws_lambda_event_source_mapping.starter.function_response_types, "ReportBatchItemFailures")
    error_message = "Partial batch responses must be enabled."
  }
  assert {
    condition     = aws_lambda_function_event_invoke_config.validate.maximum_retry_attempts == 2 && aws_lambda_function_event_invoke_config.validate.maximum_event_age_in_seconds == 3600
    error_message = "Validate async retry/age must match the runbook."
  }
  assert {
    condition     = length(aws_iam_role_policy.tv2) == 0 && length(aws_s3_bucket_notification.upload) == 0
    error_message = "A reusable module must not mutate existing roles/notifications by default."
  }
  assert {
    condition = alltrue([
      for key, alarm in aws_cloudwatch_metric_alarm.native :
      alarm.datapoints_to_alarm == 1 && alarm.evaluation_periods == 2 &&
      alarm.period == 60 && alarm.threshold == 1 && alarm.treat_missing_data == "notBreaching"
      if key != "queue_age"
    ])
    error_message = "Error and failure-queue alarms must require one of two one-minute datapoints at or above 1."
  }
  assert {
    condition = (
      aws_cloudwatch_metric_alarm.native["queue_age"].evaluation_periods == 2 &&
      aws_cloudwatch_metric_alarm.native["queue_age"].datapoints_to_alarm == 2 &&
      aws_cloudwatch_metric_alarm.native["queue_age"].threshold == 300
    )
    error_message = "Backlog alarms must still require two breaching periods at or above 300 seconds."
  }
}
