from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HANDLER_PATH = ROOT / "lambdas" / "start-job" / "handler.py"


def load_handler():
    specification = importlib.util.spec_from_file_location(
        "tv3_start_job_handler", HANDLER_PATH
    )
    module = importlib.util.module_from_spec(specification)
    assert specification and specification.loader
    specification.loader.exec_module(module)
    return module


class FakeTextract:
    def __init__(self):
        self.expense_calls = []
        self.document_calls = []

    def start_expense_analysis(self, **arguments):
        self.expense_calls.append(arguments)
        return {"JobId": "expense-job-1"}

    def start_document_analysis(self, **arguments):
        self.document_calls.append(arguments)
        return {"JobId": "document-job-1"}


class FakeDynamoDB:
    def __init__(self):
        self.put_calls = []

    def put_item(self, **arguments):
        self.put_calls.append(arguments)
        return {}


@pytest.fixture
def configured_environment(monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:ap-southeast-1:123:textract")
    monkeypatch.setenv("TEXTRACT_ROLE_ARN", "arn:aws:iam::123:role/textract")
    monkeypatch.setenv("JOB_CALLBACKS_TABLE", "job-callbacks")


def request(document_type="INVOICE"):
    return {
        "document_id": "doc-001",
        "user_id": "user-001",
        "document_type": document_type,
        "bucket": "upload-bucket",
        "key": "uploads/user-001/doc-001.pdf",
        "attempt": 1,
        "task_token": "secret-step-functions-token",
    }


def test_invoice_starts_expense_job_and_saves_callback(
    monkeypatch, configured_environment
):
    handler = load_handler()
    textract = FakeTextract()
    dynamodb = FakeDynamoDB()
    clients = {"textract": textract, "dynamodb": dynamodb}
    monkeypatch.setattr(handler, "_client", clients.__getitem__)
    monkeypatch.setattr(handler.time, "time", lambda: 1_700_000_000)

    result = handler.lambda_handler(request(), None)

    assert result == {
        "job_id": "expense-job-1",
        "document_id": "doc-001",
        "document_type": "INVOICE",
        "status": "PROCESSING",
    }
    assert len(textract.expense_calls) == 1
    arguments = textract.expense_calls[0]
    assert arguments["DocumentLocation"]["S3Object"] == {
        "Bucket": "upload-bucket",
        "Name": "uploads/user-001/doc-001.pdf",
    }
    assert len(arguments["ClientRequestToken"]) == 64
    assert arguments["NotificationChannel"]["SNSTopicArn"].endswith("textract")

    stored = dynamodb.put_calls[0]
    assert stored["TableName"] == "job-callbacks"
    assert stored["Item"]["job_id"] == {"S": "expense-job-1"}
    assert stored["Item"]["task_token"] == {
        "S": "secret-step-functions-token"
    }
    assert stored["Item"]["ttl"] == {
        "N": str(1_700_000_000 + handler.CALLBACK_TTL_SECONDS)
    }


def test_transcript_starts_table_and_form_analysis(
    monkeypatch, configured_environment
):
    handler = load_handler()
    textract = FakeTextract()
    dynamodb = FakeDynamoDB()
    clients = {"textract": textract, "dynamodb": dynamodb}
    monkeypatch.setattr(handler, "_client", clients.__getitem__)

    result = handler.lambda_handler(request("TRANSCRIPT"), None)

    assert result["job_id"] == "document-job-1"
    assert not textract.expense_calls
    assert textract.document_calls[0]["FeatureTypes"] == ["TABLES", "FORMS"]


def test_request_token_is_stable_for_step_function_retry():
    handler = load_handler()
    first = handler._validated_request(request())
    second = handler._validated_request(request())

    assert handler._request_token(first) == handler._request_token(second)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("bucket", ""),
        ("document_type", "OTHER"),
        ("task_token", None),
        ("attempt", 0),
    ],
)
def test_invalid_step_functions_input_is_rejected(field_name, value):
    handler = load_handler()
    event = request()
    event[field_name] = value

    with pytest.raises(ValueError):
        handler._validated_request(event)


def test_missing_runtime_configuration_is_reported(monkeypatch):
    handler = load_handler()
    for name in ("SNS_TOPIC_ARN", "TEXTRACT_ROLE_ARN", "JOB_CALLBACKS_TABLE"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="JOB_CALLBACKS_TABLE"):
        handler._settings()
