import json
import traceback
from dataclasses import replace
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

import handler
from helpers import JPG_BYTES, PDF_BYTES, PNG_BYTES
from repository import DocumentRepository
from s3_event import InvalidKeyError, S3Object
from test_handler import aws_case, document, upload  # reuse the in-memory AWS fixture


@pytest.mark.parametrize("name,body", [
    ("a.pdf", PDF_BYTES), ("a.jpg", JPG_BYTES), ("a.jpeg", JPG_BYTES),
    ("a.png", PNG_BYTES), ("hóa đơn + tháng 1.PDF", PDF_BYTES),
])
def test_valid_format_and_unicode_paths(aws_case, name, body):
    deps, table = aws_case
    obj = upload(aws_case, file_name=name, body=body)
    assert handler.process_object(obj, deps, "r1") == "QUEUED"
    response = deps.sqs.receive_message(QueueUrl=deps.settings.queue_url)
    msg = json.loads(response["Messages"][0]["Body"])
    assert (msg["file_name"], msg["key"], msg["etag"]) == (name, obj.key, obj.etag)
    assert document(table)["s3_key"] == obj.key


@pytest.mark.parametrize("character", ["\ufffe", "\uffff"])
def test_accepted_key_survives_sqs_character_validation(aws_case, monkeypatch, character):
    deps, table = aws_case
    send = deps.sqs.send_message

    def strict_send(**kwargs):
        # Model the documented SQS constraint missing from Moto.
        if any(
            not (ord(c) in (9, 10, 13) or 0x20 <= ord(c) <= 0xD7FF
                 or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
            for c in kwargs["MessageBody"]
        ):
            raise ClientError({"Error": {"Code": "InvalidMessageContents"}}, "SendMessage")
        return send(**kwargs)

    monkeypatch.setattr(deps.sqs, "send_message", strict_send)
    obj = upload(aws_case, file_name=f"invoice{character}.pdf")
    assert handler.process_object(obj, deps, "unicode-transport") == "QUEUED"
    message = json.loads(deps.sqs.receive_message(QueueUrl=deps.settings.queue_url)["Messages"][0]["Body"])
    assert message["key"] == document(table)["s3_key"] == obj.key


@pytest.mark.parametrize("body,limit,reason", [
    (b"", 100, "FILE_EMPTY"),
    (PDF_BYTES, len(PDF_BYTES) - 1, "FILE_TOO_LARGE"),
    (PNG_BYTES, 1000, "CONTENT_MISMATCH"),
])
def test_rejections_have_no_sqs_message(aws_case, body, limit, reason):
    deps, table = aws_case
    deps.settings = replace(deps.settings, max_file_size_bytes=limit)
    obj = upload(aws_case, body=body)
    assert handler.process_object(obj, deps, "r1") == "REJECTED"
    assert document(table)["reject_reason"] == reason
    assert "Messages" not in deps.sqs.receive_message(QueueUrl=deps.settings.queue_url)


def test_invalid_document_type_is_rejected(aws_case):
    deps, table = aws_case
    obj = upload(aws_case)
    table.update_item(Key=deps.repo.key("test-user-1", "11111111-2222-3333-4444-555555555555"),
                      UpdateExpression="SET document_type = :t", ExpressionAttributeValues={":t": ["bad"]})
    assert handler.process_object(obj, deps, "r1") == "REJECTED"
    assert document(table)["reject_reason"] == "INVALID_DOCUMENT_TYPE"


def test_exact_size_limit_is_allowed(aws_case):
    deps, _ = aws_case
    deps.settings = replace(deps.settings, max_file_size_bytes=len(PDF_BYTES))
    assert handler.process_object(upload(aws_case), deps, "r1") == "QUEUED"


def test_send_failure_preserves_pending(aws_case, monkeypatch):
    deps, table = aws_case
    obj = upload(aws_case)

    def deny(**kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "SendMessage")

    monkeypatch.setattr(deps.sqs, "send_message", deny)
    with pytest.raises(ClientError):
        handler.process_object(obj, deps, "r1")
    assert document(table)["status"] == "UPLOAD_PENDING"


def test_overwrite_detected_before_publishing(aws_case):
    deps, table = aws_case
    obj = upload(aws_case)
    deps.s3.put_object(Bucket=obj.bucket, Key=obj.key, Body=PDF_BYTES + b"changed")
    with pytest.raises(RuntimeError):
        handler.process_object(obj, deps, "r1")
    assert document(table)["status"] == "UPLOAD_PENDING"
    assert "Messages" not in deps.sqs.receive_message(QueueUrl=deps.settings.queue_url)


def test_invalid_key_and_wrong_bucket_are_not_silently_acked(aws_case):
    deps, _ = aws_case
    with pytest.raises(InvalidKeyError):
        handler.process_object(S3Object("b", "uploads/bad", 1, "etag", "ObjectCreated:Put"), deps, "r1")
    deps.settings = replace(deps.settings, upload_bucket="expected")
    with pytest.raises(ValueError):
        handler.process_object(S3Object("other", "uploads/u/d/a.pdf", 1, "etag", "ObjectCreated:Put"), deps, "r1")


def test_record_filename_mismatch_preserves_pending(aws_case):
    deps, table = aws_case
    obj = upload(aws_case)
    with pytest.raises(RuntimeError):
        handler.process_object(replace(obj, key=obj.key.replace("test.pdf", "other.pdf")), deps, "r1")
    assert document(table)["status"] == "UPLOAD_PENDING"


def test_logs_do_not_include_filename_key_or_reject_detail(aws_case, capsys):
    deps, _ = aws_case
    obj = upload(aws_case, file_name="private-customer.secret-extension", body=b"x")
    handler.process_object(obj, deps, "r1")
    output = capsys.readouterr().out
    assert obj.key not in output
    assert obj.key.rsplit("/", 1)[1] not in output
    assert "secret-extension" not in output


def test_repository_condition_cannot_create_missing_document(aws_case):
    deps, table = aws_case
    repo = DocumentRepository(table)
    assert repo.mark_rejected("absent", "absent", reason="FILE_EMPTY", detail="size=0", now="now") is False
    assert repo.get("absent", "absent") is None


@pytest.mark.parametrize("status", ["QUEUED", "PROCESSING", "SUCCEEDED", "REJECTED", "FAILED"])
def test_existing_status_never_overwritten(aws_case, status):
    deps, table = aws_case
    obj = upload(aws_case)
    key = deps.repo.key("test-user-1", "11111111-2222-3333-4444-555555555555")
    table.update_item(Key=key, UpdateExpression="SET #s=:s", ExpressionAttributeNames={"#s": "status"},
                      ExpressionAttributeValues={":s": status})
    assert handler.process_object(obj, deps, "r1") == "DUPLICATE"
    assert document(table)["status"] == status


def test_handler_reads_no_dependencies_for_s3_test_event(aws_case, monkeypatch):
    deps, _ = aws_case
    monkeypatch.setattr(handler, "get_dependencies", lambda: deps)
    assert handler.lambda_handler({"Service": "Amazon S3", "Event": "s3:TestEvent"}, SimpleNamespace(aws_request_id="r1")) == {"outcomes": []}


def test_lambda_traceback_does_not_expose_sdk_error_message(monkeypatch, capsys):
    def deny():
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "uploads/private-customer.pdf"}}, "GetObject")

    monkeypatch.setattr(handler, "get_dependencies", deny)
    try:
        handler.lambda_handler({}, SimpleNamespace(aws_request_id="r1"))
    except handler.ValidateProcessingError:
        rendered = traceback.format_exc()
    else:
        pytest.fail("The invocation must fail so async retry stays active")
    assert "private-customer" not in rendered
    assert "private-customer" not in capsys.readouterr().out
