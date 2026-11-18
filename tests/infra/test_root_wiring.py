"""Khóa cấu hình root Terraform để 4 lỗi nối dây không quay lại.

Các test này chỉ đọc file, không gọi AWS. Mục đích là bắt lỗi lệch giữa
code Lambda và biến môi trường/trigger do Terraform root tạo.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def _read(name: str) -> str:
    return (INFRA / name).read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_validate_receives_tv2_environment_contract():
    block = _between(
        _read("lambda.tf"),
        'resource "aws_lambda_function" "validate"',
        'resource "aws_lambda_function" "workflow_starter"',
    )
    for setting in (
        "DOCUMENTS_TABLE",
        "QUEUE_URL",
        "UPLOAD_BUCKET",
        "UPLOAD_PREFIX",
        "MAX_FILE_SIZE_BYTES",
    ):
        assert setting in block

    # Tên biến cũ của TV5 không được quay lại: code TV2 không đọc chúng.
    assert "SQS_QUEUE_URL" not in block
    assert "SQS_DLQ_URL" not in block


def test_s3_upload_bucket_triggers_validate_lambda():
    source = _read("s3.tf")
    assert 'resource "aws_s3_bucket_notification" "upload"' in source
    assert 'resource "aws_lambda_permission" "s3_invoke_validate"' in source
    assert 'principal     = "s3.amazonaws.com"' in source
    assert 'filter_prefix       = "uploads/"' in source
    assert "aws_lambda_function.validate.arn" in source


def test_workflow_starter_is_wired_to_processing_queue():
    lambda_source = _read("lambda.tf")
    starter = _between(
        lambda_source,
        'resource "aws_lambda_function" "workflow_starter"',
        'resource "aws_lambda_function" "start_job"',
    )
    assert 'handler          = "app.lambda_handler"' in starter
    for setting in ("DOCUMENTS_TABLE", "STATE_MACHINE_ARN", "UPLOAD_BUCKET", "UPLOAD_PREFIX"):
        assert setting in starter

    sqs_source = _read("sqs.tf")
    assert 'resource "aws_lambda_event_source_mapping" "starter"' in sqs_source
    assert "aws_sqs_queue.processing.arn" in sqs_source
    assert "aws_lambda_function.workflow_starter.arn" in sqs_source


def test_lambda_role_can_consume_queue_and_start_execution():
    policy = _between(
        _read("iam.tf"),
        'resource "aws_iam_role_policy" "lambda_pipeline"',
        "resource \"aws_iam_role_policy\" \"workflow\"",
    )
    for action in (
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "states:StartExecution",
        "states:DescribeExecution",
    ):
        assert action in policy


def test_documents_table_has_status_and_type_indexes_and_pitr():
    block = _between(
        _read("dynamodb.tf"),
        'resource "aws_dynamodb_table" "documents"',
        'resource "aws_dynamodb_table" "job_callbacks"',
    )
    assert 'name            = "GSI-status"' in block
    assert 'name            = "GSI-type"' in block
    assert 'hash_key        = "status"' in block
    assert 'hash_key        = "document_type"' in block
    assert 'range_key       = "created_at"' in block
    assert "point_in_time_recovery" in block
    assert "enabled = true" in block
