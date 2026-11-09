import json

import pytest
from botocore.exceptions import ClientError

import app
import messages
from helpers import make_sqs_record

STATE_MACHINE = "arn:aws:states:ap-southeast-1:123456789012:stateMachine:demo"


class FakeTable:
    def __init__(self, item):
        self.item = item

    def get_item(self, **kwargs):
        return {"Item": self.item} if self.item else {}


class FakeSfn:
    def __init__(self):
        self.executions = {}

    def start_execution(self, *, stateMachineArn, name, input):
        if name in self.executions:
            raise ClientError(
                {"Error": {"Code": "ExecutionAlreadyExists", "Message": "duplicate"}},
                "StartExecution",
            )
        self.executions[name] = input

    def describe_execution(self, *, executionArn):
        return {"input": self.executions[executionArn.rsplit(":", 1)[-1]]}


@pytest.fixture
def case():
    msg = messages.build_message(
        document_id="d1", user_id="u1", document_type="INVOICE",
        bucket="idp-upload-test", key="uploads/u1/d1/a.pdf", file_name="a.pdf",
        content_type="application/pdf", size_bytes=10, etag="abc",
        request_id="r1", queued_at="2026-11-07T00:00:00Z",
    )
    item = {
        "status": "QUEUED", "document_type": "INVOICE", "file_name": "a.pdf",
        "s3_key": msg["key"], "object_etag": "abc", "size_bytes": 10,
    }
    deps = app.Dependencies(FakeTable(item), FakeSfn(), STATE_MACHINE, "idp-upload-test")
    return msg, deps


def test_starts_once_even_when_request_id_changes(case):
    msg, deps = case
    assert app.process_message(json.dumps(msg), deps) == "STARTED"
    retry = {**msg, "request_id": "r2", "queued_at": "2026-11-07T00:01:00Z"}
    assert app.process_message(json.dumps(retry), deps) == "DUPLICATE"
    assert len(deps.sfn.executions) == 1


def test_pending_record_retries_without_starting(case):
    msg, deps = case
    deps.table.item["status"] = "UPLOAD_PENDING"
    with pytest.raises(app.NotReadyError):
        app.process_message(json.dumps(msg), deps)
    assert deps.sfn.executions == {}


def test_same_document_id_different_user_gets_different_execution_name(case):
    msg, _ = case
    other = {**msg, "user_id": "u2"}
    assert app.execution_name(msg) != app.execution_name(other)


def test_partial_batch_retries_only_bad_record(case, monkeypatch):
    msg, deps = case
    monkeypatch.setattr(app, "get_dependencies", lambda: deps)
    event = {"Records": [
        make_sqs_record(json.dumps(msg), "good"),
        make_sqs_record("{bad json", "bad"),
    ]}
    result = app.lambda_handler(event, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    assert len(deps.sfn.executions) == 1
