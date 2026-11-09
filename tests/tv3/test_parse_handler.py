from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lambdas.parse import handler


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def dynamodb_item(**overrides):
    values = {
        "job_id": "job-001",
        "task_token": "secret-task-token",
        "document_id": "doc-001",
        "user_id": "user-001",
        "document_type": "INVOICE",
    }
    values.update(overrides)
    return {name: {"S": value} for name, value in values.items()}


class FakeDynamoDB:
    def __init__(self, item):
        self.item = item
        self.update_calls = []

    def get_item(self, **arguments):
        return {"Item": self.item}

    def update_item(self, **arguments):
        self.update_calls.append(arguments)
        return {}


class FakeTextract:
    def __init__(self, pages):
        self.pages = list(pages)
        self.expense_calls = []
        self.document_calls = []

    def get_expense_analysis(self, **arguments):
        self.expense_calls.append(arguments)
        return self.pages.pop(0)

    def get_document_analysis(self, **arguments):
        self.document_calls.append(arguments)
        return self.pages.pop(0)


class FakeS3:
    def __init__(self):
        self.put_calls = []

    def put_object(self, **arguments):
        self.put_calls.append(arguments)
        return {}


class FakeStepFunctions:
    def __init__(self):
        self.success_calls = []
        self.failure_calls = []

    def send_task_success(self, **arguments):
        self.success_calls.append(arguments)
        return {}

    def send_task_failure(self, **arguments):
        self.failure_calls.append(arguments)
        return {}


def sns_event(status="SUCCEEDED", api="StartExpenseAnalysis"):
    message = {
        "JobId": "job-001",
        "Status": status,
        "API": api,
    }
    return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}


@pytest.fixture(autouse=True)
def configured_environment(monkeypatch):
    monkeypatch.setenv("JOB_CALLBACKS_TABLE", "job-callbacks")
    monkeypatch.setenv("S3_RESULTS_BUCKET", "results-bucket")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "80")


def install_clients(monkeypatch, *, item, pages):
    clients = {
        "dynamodb": FakeDynamoDB(item),
        "textract": FakeTextract(pages),
        "s3": FakeS3(),
        "stepfunctions": FakeStepFunctions(),
    }
    monkeypatch.setattr(handler, "_client", clients.__getitem__)
    return clients


def test_successful_invoice_callback_stores_raw_and_resumes_workflow(monkeypatch):
    raw = load_json(FIXTURES / "textract" / "invoice.json")
    expected = load_json(FIXTURES / "expected" / "invoice.json")
    clients = install_clients(
        monkeypatch, item=dynamodb_item(), pages=[raw]
    )

    result = handler.lambda_handler(sns_event(), None)

    assert result["processed"] == 1
    assert result["results"][0]["status"] == "SUCCEEDED"
    assert len(clients["s3"].put_calls) == 1
    stored = clients["s3"].put_calls[0]
    assert stored["Bucket"] == "results-bucket"
    assert stored["Key"].startswith("user_id=user-001/year=")
    assert stored["Key"].endswith("/doc-001.json")
    assert json.loads(stored["Body"].decode("utf-8")) == raw

    callback = clients["stepfunctions"].success_calls[0]
    callback_output = json.loads(callback["output"])
    assert callback["taskToken"] == "secret-task-token"
    assert callback_output["status"] == "SUCCEEDED"
    assert callback_output["confidence"] == expected["confidence"]
    assert callback_output["extracted"] == expected["extracted"]
    assert clients["textract"].expense_calls[0]["MaxResults"] == 20
    assert clients["dynamodb"].update_calls


def test_low_confidence_result_is_marked_for_review(monkeypatch):
    raw = load_json(FIXTURES / "textract" / "invoice.json")
    vendor = next(
        field
        for field in raw["ExpenseDocuments"][0]["SummaryFields"]
        if field["Type"]["Text"] == "VENDOR_NAME"
    )
    vendor["ValueDetection"]["Confidence"] = 40.0
    clients = install_clients(
        monkeypatch, item=dynamodb_item(), pages=[raw]
    )

    result = handler.lambda_handler(sns_event(), None)

    assert result["results"][0]["status"] == "NEEDS_REVIEW"
    output = json.loads(clients["stepfunctions"].success_calls[0]["output"])
    assert output["status"] == "NEEDS_REVIEW"
    assert any(warning["code"] == "LOW_CONFIDENCE" for warning in output["warnings"])


def test_transcript_callback_uses_document_analysis(monkeypatch):
    raw = load_json(FIXTURES / "textract" / "transcript.json")
    clients = install_clients(
        monkeypatch,
        item=dynamodb_item(document_type="TRANSCRIPT"),
        pages=[raw],
    )

    result = handler.lambda_handler(
        sns_event(api="StartDocumentAnalysis"), None
    )

    assert result["results"][0]["status"] == "SUCCEEDED"
    assert len(clients["textract"].document_calls) == 1
    assert not clients["textract"].expense_calls


def test_all_textract_pages_are_collected(monkeypatch):
    pages = [
        {"Blocks": [{"Id": "one"}], "NextToken": "page-2"},
        {"Blocks": [{"Id": "two"}]},
    ]
    clients = install_clients(
        monkeypatch,
        item=dynamodb_item(document_type="TRANSCRIPT"),
        pages=pages,
    )

    combined = handler._get_all_results("job-001", "TRANSCRIPT")

    assert combined["Blocks"] == [{"Id": "one"}, {"Id": "two"}]
    assert clients["textract"].document_calls[0]["MaxResults"] == 1_000
    assert clients["textract"].document_calls[1]["NextToken"] == "page-2"


def test_failed_textract_job_resumes_failure_branch(monkeypatch):
    clients = install_clients(
        monkeypatch, item=dynamodb_item(), pages=[]
    )

    result = handler.lambda_handler(sns_event(status="FAILED"), None)

    assert result["results"][0]["status"] == "FAILED"
    assert not clients["stepfunctions"].success_calls
    failure = clients["stepfunctions"].failure_calls[0]
    assert failure["taskToken"] == "secret-task-token"
    assert failure["error"] == "TextractExecutionError"


def test_duplicate_completed_callback_is_ignored(monkeypatch):
    clients = install_clients(
        monkeypatch,
        item=dynamodb_item(callback_status="COMPLETED"),
        pages=[],
    )

    result = handler.lambda_handler(sns_event(), None)

    assert result["results"][0]["status"] == "ALREADY_COMPLETED"
    assert not clients["stepfunctions"].success_calls
    assert not clients["stepfunctions"].failure_calls


def test_partial_textract_result_requires_review(monkeypatch):
    raw = copy.deepcopy(load_json(FIXTURES / "textract" / "invoice.json"))
    clients = install_clients(
        monkeypatch, item=dynamodb_item(), pages=[raw]
    )

    result = handler.lambda_handler(
        sns_event(status="PARTIAL_SUCCESS"), None
    )

    assert result["results"][0]["status"] == "NEEDS_REVIEW"
    output = json.loads(clients["stepfunctions"].success_calls[0]["output"])
    assert any(
        warning["code"] == "TEXTRACT_PARTIAL_SUCCESS"
        for warning in output["warnings"]
    )


def test_invalid_sns_message_is_rejected():
    event = {"Records": [{"Sns": {"Message": "not-json"}}]}

    with pytest.raises(ValueError, match="not valid JSON"):
        handler.lambda_handler(event, None)
