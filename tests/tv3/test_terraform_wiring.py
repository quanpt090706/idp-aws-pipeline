from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def _read(name: str) -> str:
    return (INFRA / name).read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_start_job_receives_all_required_runtime_settings():
    source = _read("lambda.tf")
    source = _between(
        source,
        'resource "aws_lambda_function" "start_job"',
        'resource "aws_lambda_function" "parse"',
    )
    for setting in ("SNS_TOPIC_ARN", "TEXTRACT_ROLE_ARN", "JOB_CALLBACKS_TABLE"):
        assert setting in source


def test_parse_receives_callback_table_results_bucket_and_threshold():
    source = _read("lambda.tf")
    source = _between(
        source,
        'resource "aws_lambda_function" "parse"',
        'resource "aws_lambda_function" "notification"',
    )
    for setting in (
        "JOB_CALLBACKS_TABLE",
        "S3_RESULTS_BUCKET",
        "CONFIDENCE_THRESHOLD",
    ):
        assert setting in source


def test_sns_completion_topic_invokes_parse_lambda():
    source = _read("sns.tf")
    assert 'principal     = "sns.amazonaws.com"' in source
    assert "aws_sns_topic_subscription" in source
    assert "aws_lambda_function.parse.arn" in source


def test_callback_ttl_attribute_matches_start_job_contract():
    source = _read("dynamodb.tf")
    assert 'attribute_name = "ttl"' in source
    assert "ttl_expiry" not in source


def test_state_machine_uses_notification_lambda_and_workflow_role():
    source = _read("step_functions.tf")
    assert "role_arn = local.workflow_role_arn" in source
    assert "NOTIFICATION_LAMBDA_ARN = aws_lambda_function.notification.arn" in source


def test_textract_role_and_pass_role_are_configured():
    source = _read("iam.tf")
    assert 'Service = "textract.amazonaws.com"' in source
    assert 'Action   = "sns:Publish"' in source
    assert 'Action   = "iam:PassRole"' in source
    assert '"iam:PassedToService" = "textract.amazonaws.com"' in source
