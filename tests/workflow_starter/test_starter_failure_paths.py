import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import app
import rules
from helpers import make_sqs_record
from s3_event import parse_s3_event, parse_upload_key
from test_app import case


def test_handoff_fixtures_match_actual_workflow_input():
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    message = json.loads((fixtures / "sqs_message.json").read_text(encoding="utf-8"))
    payload = json.loads((fixtures / "step_functions_input.json").read_text(encoding="utf-8"))
    assert {key: message[key] for key in app.INPUT_FIELDS} == payload
    assert len(app.execution_name(message)) <= 80
    event = json.loads((fixtures / "s3_event_pdf.json").read_text(encoding="utf-8"))
    obj = parse_s3_event(event)[0]
    upload_key = parse_upload_key(obj.key)
    assert {
        "user_id": upload_key.user_id, "document_id": upload_key.document_id,
        "file_name": upload_key.file_name, "bucket": obj.bucket, "key": obj.key,
        "size_bytes": obj.size, "etag": obj.etag,
    } == {key: message[key] for key in (
        "user_id", "document_id", "file_name", "bucket", "key", "size_bytes", "etag",
    )}


@pytest.mark.parametrize("file_name", [".pdf", "..PDF", ".jpg", ".JPEG", ".png", "...PNG"])
def test_starter_accepts_extensions_accepted_by_validate(case, file_name):
    msg, deps = case
    assert rules.validate_basic(file_name, msg["size_bytes"], 10485760).ok
    msg.update(file_name=file_name, key=f"uploads/u1/d1/{file_name}",
               content_type=rules.content_type_for(file_name))
    deps.table.item.update(file_name=file_name, s3_key=msg["key"])
    assert app.process_message(json.dumps(msg), deps) == "STARTED"


@pytest.mark.parametrize("change", [
    {"schema_version": "2.0"}, {"attempt": 2}, {"attempt": True},
    {"size_bytes": 0}, {"size_bytes": True}, {"user_id": "u 1"},
    {"document_id": "d\n"}, {"bucket": "other"}, {"key": "other"},
    {"file_name": "a/b.pdf"}, {"file_name": "a\\b.pdf"},
    {"file_name": "a\n.pdf"}, {"file_name": "a" * 256},
    {"content_type": "image/png"}, {"etag": ""}, {"etag": 123},
])
def test_invalid_messages_fail_before_start(case, change):
    msg, deps = case
    with pytest.raises(ValueError):
        app.process_message(json.dumps({**msg, **change}), deps)
    assert deps.sfn.executions == {}


@pytest.mark.parametrize("body", ["{}", "[]", "null", "{bad"])
def test_non_contract_json(case, body):
    _, deps = case
    with pytest.raises(ValueError):
        app.process_message(body, deps)


def test_conflicting_existing_execution_is_not_acked(case):
    msg, deps = case
    name = app.execution_name(msg)
    deps.sfn.executions[name] = json.dumps({"different": "input"})
    with pytest.raises(RuntimeError, match="input"):
        app.process_message(json.dumps(msg), deps)


@pytest.mark.parametrize("status", ["QUEUED", "PROCESSING", "SUCCEEDED"])
@pytest.mark.parametrize("field,value", [
    ("attempt", True), ("attempt", 1.0), ("size_bytes", 10.0),
])
def test_existing_execution_with_different_json_type_is_not_acked(case, status, field, value):
    msg, deps = case
    deps.table.item["status"] = status
    payload = {key: msg[key] for key in app.INPUT_FIELDS}
    deps.sfn.executions[app.execution_name(msg)] = json.dumps({**payload, field: value})
    with pytest.raises(RuntimeError, match="input"):
        app.process_message(json.dumps(msg), deps)


def test_equivalent_existing_input_with_different_formatting_is_duplicate(case):
    msg, deps = case
    payload = {key: msg[key] for key in reversed(app.INPUT_FIELDS)}
    deps.sfn.executions[app.execution_name(msg)] = json.dumps(payload, indent=2)
    assert app.process_message(json.dumps(msg), deps) == "DUPLICATE"


def test_terminal_document_verifies_existing_execution(case):
    msg, deps = case
    app.process_message(json.dumps(msg), deps)
    deps.table.item["status"] = "SUCCEEDED"
    assert app.process_message(json.dumps(msg), deps) == "DUPLICATE"
    assert len(deps.sfn.executions) == 1


@pytest.mark.parametrize("status", ["REJECTED", "UNKNOWN"])
def test_incompatible_document_status_fails(case, status):
    msg, deps = case
    deps.table.item["status"] = status
    with pytest.raises(RuntimeError):
        app.process_message(json.dumps(msg), deps)


def test_missing_record_retries(case):
    msg, deps = case
    deps.table.item = None
    with pytest.raises(app.NotReadyError):
        app.process_message(json.dumps(msg), deps)


def test_access_denied_returns_partial_failure_without_body_in_log(case, monkeypatch, capsys):
    msg, deps = case

    def deny(**kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": msg["key"]}}, "StartExecution")

    monkeypatch.setattr(deps.sfn, "start_execution", deny)
    monkeypatch.setattr(app, "get_dependencies", lambda: deps)
    response = app.lambda_handler({"Records": [make_sqs_record(json.dumps(msg), "denied")]}, None)
    assert response == {"batchItemFailures": [{"itemIdentifier": "denied"}]}
    assert msg["key"] not in capsys.readouterr().out


def test_queued_record_must_match_message(case):
    msg, deps = case
    deps.table.item["object_etag"] = "different-object"
    with pytest.raises(RuntimeError):
        app.process_message(json.dumps(msg), deps)
    assert deps.sfn.executions == {}


@pytest.mark.parametrize("suffix", ["", ":dev", ":42"])
def test_execution_arn_supports_state_machine_alias_and_version(suffix):
    machine = "arn:aws:states:us-east-1:123456789012:stateMachine:demo" + suffix
    assert app.execution_arn(machine, "doc-abc") == "arn:aws:states:us-east-1:123456789012:execution:demo:doc-abc"
