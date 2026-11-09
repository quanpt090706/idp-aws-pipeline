import boto3
import pytest
from moto import mock_aws

from config import Settings
from handler import Dependencies, MissingDocumentError, process_object
from helpers import PDF_BYTES, make_s3_event
from repository import DocumentRepository
from s3_event import parse_s3_event

REGION = "ap-southeast-1"
BUCKET = "idp-upload-test"
DOC_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def aws_case():
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
        )
        ddb = boto3.resource("dynamodb", region_name=REGION)
        table = ddb.create_table(
            TableName="DocumentsTest",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName="processing-test")["QueueUrl"]
        deps = Dependencies(Settings("DocumentsTest", queue_url), s3, sqs, DocumentRepository(table))
        yield deps, table


def upload(aws_case, *, file_name="test.pdf", body=PDF_BYTES, create_record=True):
    deps, table = aws_case
    key = f"uploads/test-user-1/{DOC_ID}/{file_name}"
    if create_record:
        table.put_item(Item={
            "PK": "USER#test-user-1", "SK": f"DOC#{DOC_ID}",
            "user_id": "test-user-1", "document_id": DOC_ID,
            "file_name": file_name, "document_type": "INVOICE",
            "status": "UPLOAD_PENDING",
        })
    put = deps.s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    event = make_s3_event(BUCKET, key, len(body), etag=put["ETag"].strip('"'))
    return parse_s3_event(event)[0]


def document(table):
    return table.get_item(
        Key={"PK": "USER#test-user-1", "SK": f"DOC#{DOC_ID}"}
    )["Item"]


def test_valid_pdf_queued_once(aws_case):
    deps, table = aws_case
    obj = upload(aws_case)
    assert process_object(obj, deps, "request-1") == "QUEUED"
    assert process_object(obj, deps, "request-2") == "DUPLICATE"
    assert document(table)["status"] == "QUEUED"
    assert document(table)["object_etag"] == obj.etag
    messages = deps.sqs.receive_message(QueueUrl=deps.settings.queue_url).get("Messages", [])
    assert len(messages) == 1


def test_invalid_extension_rejected_without_queueing(aws_case):
    deps, table = aws_case
    obj = upload(aws_case, file_name="bad.exe", body=b"MZfake")
    assert process_object(obj, deps, "request-1") == "REJECTED"
    assert document(table)["reject_reason"] == "UNSUPPORTED_EXTENSION"
    assert deps.sqs.receive_message(QueueUrl=deps.settings.queue_url).get("Messages", []) == []


def test_missing_document_record_is_retryable(aws_case):
    deps, _ = aws_case
    obj = upload(aws_case, create_record=False)
    with pytest.raises(MissingDocumentError):
        process_object(obj, deps, "request-1")


def test_sqs_sent_but_ddb_update_fails(aws_case, monkeypatch):
    deps, table = aws_case
    obj = upload(aws_case)

    def fail_update(*args, **kwargs):
        raise RuntimeError("DynamoDB tạm lỗi")

    monkeypatch.setattr(deps.repo, "mark_queued", fail_update)
    with pytest.raises(RuntimeError):
        process_object(obj, deps, "request-1")
    assert document(table)["status"] == "UPLOAD_PENDING"
    assert len(deps.sqs.receive_message(QueueUrl=deps.settings.queue_url)["Messages"]) == 1
    # Bước 7 kiểm tra Starter phải retry message này, chưa gọi StartExecution.
