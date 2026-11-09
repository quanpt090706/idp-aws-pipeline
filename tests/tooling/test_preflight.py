import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("tv2_preflight_test", ROOT / "scripts" / "tv2_preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def config():
    result = dict.fromkeys(preflight.REQUIRED, "test")
    result["expected_account_id"] = "123456789012"
    return result


def test_empty_example_blocks_before_using_aws():
    with pytest.raises(ValueError, match="Missing"):
        preflight.load_config(ROOT / "docs" / "tv2" / "aws-dev.example.json")


def test_loads_terraform_json_output(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tv2_config": {"value": config()}}), encoding="utf-8")
    assert preflight.load_config(path) == config()


def test_account_guard_stops_before_resource_access(monkeypatch):
    calls = []

    class FakeSession:
        def client(self, service):
            calls.append(service)
            assert service == "sts"
            return self

        def get_caller_identity(self):
            return {"Account": "999999999999"}

    monkeypatch.setattr(preflight.boto3, "Session", lambda **kwargs: FakeSession())
    with pytest.raises(ValueError, match="account"):
        preflight.checked_session(config(), "academy-lab")
    assert calls == ["sts"]


@pytest.fixture
def environment():
    cfg = {
        **config(), "region": "us-east-1", "upload_bucket": "idp-test",
        "documents_table": "Documents", "validate_function_name": "validate",
        "starter_function_name": "starter",
        "state_machine_arn": "arn:aws:states:us-east-1:123456789012:stateMachine:test",
        "processing_queue_url": "processing", "processing_dlq_url": "dlq",
        "validate_failures_queue_url": "failures",
    }
    clients = {name: MagicMock() for name in ("s3", "dynamodb", "stepfunctions", "sqs", "lambda")}
    session = MagicMock()
    session.client.side_effect = clients.__getitem__
    clients["s3"].get_bucket_location.return_value = {"LocationConstraint": None}
    clients["dynamodb"].describe_table.return_value = {"Table": {
        "KeySchema": [{"KeyType": "HASH", "AttributeName": "PK"}, {"KeyType": "RANGE", "AttributeName": "SK"}],
        "AttributeDefinitions": [{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
    }}
    clients["stepfunctions"].describe_state_machine.return_value = {"type": "STANDARD"}
    queue_arn = "arn:aws:sqs:us-east-1:123456789012:"
    queues = {
        "processing": {"QueueArn": queue_arn + "processing", "VisibilityTimeout": "180",
                       "MessageRetentionPeriod": "345600", "RedrivePolicy": json.dumps({
                           "maxReceiveCount": 5, "deadLetterTargetArn": queue_arn + "dlq",
                       })},
        "dlq": {"QueueArn": queue_arn + "dlq", "MessageRetentionPeriod": "1209600"},
        "failures": {"QueueArn": queue_arn + "failures", "MessageRetentionPeriod": "1209600"},
    }
    clients["sqs"].get_queue_attributes.side_effect = lambda QueueUrl, **kwargs: {"Attributes": queues[QueueUrl]}
    function_arn = "arn:aws:lambda:us-east-1:123456789012:function:validate"
    common_env = {"DOCUMENTS_TABLE": "Documents", "UPLOAD_BUCKET": "idp-test", "UPLOAD_PREFIX": "uploads/"}
    functions = {
        "validate": {"Handler": "handler.lambda_handler", "FunctionArn": function_arn,
                     "Environment": {"Variables": {**common_env, "QUEUE_URL": "processing"}}},
        "starter": {"Handler": "app.lambda_handler", "Timeout": 30,
                    "Environment": {"Variables": {**common_env, "STATE_MACHINE_ARN": cfg["state_machine_arn"]}}},
    }
    clients["lambda"].get_function_configuration.side_effect = lambda FunctionName: functions[FunctionName]
    clients["lambda"].list_event_source_mappings.return_value = {"EventSourceMappings": [
        {"State": "Enabled", "FunctionResponseTypes": ["ReportBatchItemFailures"]},
    ]}
    clients["lambda"].get_function_event_invoke_config.return_value = {
        "MaximumRetryAttempts": 2, "MaximumEventAgeInSeconds": 3600,
        "DestinationConfig": {"OnFailure": {"Destination": queue_arn + "failures"}},
    }
    clients["s3"].get_bucket_notification_configuration.return_value = {"LambdaFunctionConfigurations": [{
        "LambdaFunctionArn": function_arn, "Events": ["s3:ObjectCreated:*"],
        "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "uploads/"}]}},
    }]}
    return cfg, session, clients


def test_matching_environment_passes(environment):
    cfg, session, _ = environment
    results = preflight.check_environment(cfg, session)
    assert all(check["passed"] for check in results), results


@pytest.mark.parametrize("suffix", [".pdf", ".jpg", ".png", ".exe"])
def test_notification_suffix_filter_fails_preflight(environment, suffix):
    cfg, session, clients = environment
    notification = clients["s3"].get_bucket_notification_configuration.return_value["LambdaFunctionConfigurations"][0]
    notification["Filter"]["Key"]["FilterRules"].append({"Name": "suffix", "Value": suffix})
    results = {check["check"]: check["passed"] for check in preflight.check_environment(cfg, session)}
    assert results["s3_notification"] is False


@pytest.mark.parametrize("prefix", ["other/", "uploads/user-1/", "uploads"])
def test_notification_requires_exact_upload_prefix(environment, prefix):
    cfg, session, clients = environment
    notification = clients["s3"].get_bucket_notification_configuration.return_value["LambdaFunctionConfigurations"][0]
    notification["Filter"]["Key"]["FilterRules"] = [{"Name": "prefix", "Value": prefix}]
    results = {check["check"]: check["passed"] for check in preflight.check_environment(cfg, session)}
    assert results["s3_notification"] is False


@pytest.mark.parametrize("key,attribute_type", [
    ("PK", "N"), ("PK", "B"), ("SK", "N"), ("SK", "B"), ("PK", None), ("SK", None),
])
def test_documents_keys_must_both_be_strings(environment, key, attribute_type):
    cfg, session, clients = environment
    table = clients["dynamodb"].describe_table.return_value["Table"]
    table["AttributeDefinitions"] = [attr for attr in table["AttributeDefinitions"] if attr["AttributeName"] != key]
    if attribute_type is not None:
        table["AttributeDefinitions"].append({"AttributeName": key, "AttributeType": attribute_type})
    results = {check["check"]: check["passed"] for check in preflight.check_environment(cfg, session)}
    assert results["documents_keys"] is True  # Names alone still match the contract.
    assert results["documents_key_types"] is False


def test_numeric_gsi_attribute_does_not_reject_string_primary_keys(environment):
    cfg, session, clients = environment
    table = clients["dynamodb"].describe_table.return_value["Table"]
    table["AttributeDefinitions"].append({"AttributeName": "created_at", "AttributeType": "N"})
    results = preflight.check_environment(cfg, session)
    assert all(check["passed"] for check in results), results


@pytest.mark.parametrize("value", ["0", "-1", "", "invalid", "1.5", "1", "10485759", "10485761"])
def test_validate_size_limit_must_match_demo_contract(environment, value):
    cfg, session, clients = environment
    function = clients["lambda"].get_function_configuration(FunctionName="validate")
    function["Environment"]["Variables"]["MAX_FILE_SIZE_BYTES"] = value
    results = preflight.check_environment(cfg, session)
    assert not all(check["passed"] for check in results)
    assert {check["check"]: check["passed"] for check in results}["validate_max_file_size"] is False


@pytest.mark.parametrize("value", [None, "10485760"])
def test_default_or_explicit_demo_size_limit_passes(environment, value):
    cfg, session, clients = environment
    env = clients["lambda"].get_function_configuration(FunctionName="validate")["Environment"]["Variables"]
    if value is not None:
        env["MAX_FILE_SIZE_BYTES"] = value
    results = preflight.check_environment(cfg, session)
    assert all(check["passed"] for check in results), results


@pytest.mark.parametrize("visibility,passed", [(180, False), (479, False), (480, True), (481, True)])
def test_visibility_includes_enabled_mapping_batch_window(environment, visibility, passed):
    cfg, session, clients = environment
    processing = clients["sqs"].get_queue_attributes(QueueUrl="processing")["Attributes"]
    processing["VisibilityTimeout"] = str(visibility)
    mapping = clients["lambda"].list_event_source_mappings.return_value["EventSourceMappings"][0]
    mapping["MaximumBatchingWindowInSeconds"] = 300
    results = {check["check"]: check["passed"] for check in preflight.check_environment(cfg, session)}
    assert results["visibility_timeout"] is passed
    assert results["sqs_mapping"] is True
    clients["lambda"].list_event_source_mappings.assert_called_once_with(
        FunctionName="starter", EventSourceArn=processing["QueueArn"])


def test_disabled_mapping_window_does_not_increase_required_visibility(environment):
    cfg, session, clients = environment
    clients["lambda"].list_event_source_mappings.return_value["EventSourceMappings"].append({
        "State": "Disabled", "FunctionResponseTypes": ["ReportBatchItemFailures"],
        "MaximumBatchingWindowInSeconds": 300,
    })
    results = preflight.check_environment(cfg, session)
    assert all(check["passed"] for check in results), results


def test_every_enabled_mapping_window_counts_even_without_partial_batch(environment):
    cfg, session, clients = environment
    clients["lambda"].list_event_source_mappings.return_value["EventSourceMappings"].append({
        "State": "Enabled", "MaximumBatchingWindowInSeconds": 300,
    })
    results = {check["check"]: check["passed"] for check in preflight.check_environment(cfg, session)}
    assert results["sqs_mapping"] is False
    assert results["visibility_timeout"] is False


@pytest.mark.parametrize("mappings", [[], [
    {"State": "Disabled", "FunctionResponseTypes": ["ReportBatchItemFailures"]},
]])
def test_mapping_check_requires_at_least_one_enabled_mapping(environment, mappings):
    cfg, session, clients = environment
    clients["lambda"].list_event_source_mappings.return_value["EventSourceMappings"] = mappings
    results = {check["check"]: check["passed"] for check in preflight.check_environment(cfg, session)}
    assert results["sqs_mapping"] is False
