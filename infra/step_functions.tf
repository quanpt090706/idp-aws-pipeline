################################################################################
# ORCHESTRATION LAYER (STEP FUNCTIONS STATE MACHINE)
#
# Quản lý luồng xử lý tài liệu thông minh:
# - Điều phối gọi Lambda Start-Job
# - Tạm dừng chờ callback Textract Async hoàn tất
# - Kích hoạt Lambda Parse bóc tách dữ liệu
################################################################################

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name_prefix}-pipeline-orchestrator"
  role_arn = local.lambda_role_arn

  definition = templatefile("${path.module}/step_functions/state_machine.asl.json", {
    DOCUMENTS_TABLE_NAME    = try(aws_dynamodb_table.documents.name, "${local.name_prefix}-documents")
    START_JOB_LAMBDA_ARN    = aws_lambda_function.start_job.arn
    NOTIFICATION_LAMBDA_ARN = try(aws_lambda_function.start_job.arn, "")
  })
}
