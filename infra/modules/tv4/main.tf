locals {
  documents_table_name = var.create_dynamodb_tables ? aws_dynamodb_table.documents[0].name : var.existing_documents_table_name
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.name_prefix}-pipeline"
  role_arn = var.workflow_role_arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/../../step_functions/state_machine.asl.json", {
    DOCUMENTS_TABLE_NAME  = local.documents_table_name
    START_JOB_LAMBDA_ARN  = var.start_job_lambda_arn
  })

  tags = var.tags
}
