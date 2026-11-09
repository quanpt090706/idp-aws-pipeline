"""Document API contract and ownership tests without a live AWS account."""

import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


SPEC = importlib.util.spec_from_file_location(
    "tv1_document_api", Path(__file__).resolve().parents[2] / "lambdas/document-api/handler.py"
)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


def event(method, path, user="user-1", body=None, query=None, doc_id=None):
    result = {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": user}}},
        },
        "rawPath": path,
        "queryStringParameters": query,
        "pathParameters": {"document_id": doc_id} if doc_id else None,
    }
    if body is not None:
        result["body"] = json.dumps(body)
    return result


def call(request):
    response = api.lambda_handler(request, None)
    return response["statusCode"], json.loads(response["body"])


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("DOCUMENTS_TABLE", "documents")
        monkeypatch.setenv("UPLOAD_BUCKET", "test-upload")
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="documents",
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
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-upload")
        yield table


def create(user="user-1", filename="hóa đơn.pdf", doc_type="INVOICE"):
    return call(event("POST", "/documents", user, {
        "file_name": filename,
        "content_type": "application/pdf",
        "document_type": doc_type,
    }))


def test_create_record_before_upload_and_sign_unique_put(aws):
    status, body = create()
    assert status == 201
    doc = body["document"]
    assert doc["status"] == "UPLOAD_PENDING"
    assert body["upload_headers"] == {
        "Content-Type": "application/pdf", "If-None-Match": "*"
    }
    assert body["expires_in"] == 900
    item = aws.get_item(Key={"PK": "USER#user-1", "SK": f"DOC#{doc['document_id']}"})["Item"]
    assert item["s3_key"] == f"uploads/user-1/{doc['document_id']}/hóa đơn.pdf"
    assert item["document_type"] == "INVOICE"
    assert "upload_url" in body and "X-Amz-Signature" in body["upload_url"]
    second = create()[1]["document"]["document_id"]
    assert second != doc["document_id"]


@pytest.mark.parametrize("filename,doc_type,content_type,code", [
    ("../a.pdf", "INVOICE", "application/pdf", "INVALID_FILE_NAME"),
    ("a\\b.pdf", "INVOICE", "application/pdf", "INVALID_FILE_NAME"),
    ("a\npdf.pdf", "INVOICE", "application/pdf", "INVALID_FILE_NAME"),
    ("a.exe", "INVOICE", "application/pdf", "UNSUPPORTED_FILE_TYPE"),
    ("a.pdf", "OTHER", "application/pdf", "INVALID_DOCUMENT_TYPE"),
    ("a.pdf", "INVOICE", "image/png", "UNSUPPORTED_FILE_TYPE"),
    ("😀" * 250 + ".pdf", "INVOICE", "application/pdf", "INVALID_FILE_NAME"),
])
def test_reject_bad_upload_input(aws, filename, doc_type, content_type, code):
    status, body = call(event("POST", "/documents", body={
        "file_name": filename, "document_type": doc_type, "content_type": content_type,
    }))
    assert (status, body) == (400, {"error": code})
    assert aws.scan()["Count"] == 0


def test_no_authorizer_claim_is_rejected(aws):
    request = event("GET", "/documents")
    request["requestContext"]["authorizer"] = {}
    assert call(request) == (401, {"error": "UNAUTHORIZED"})


def test_list_is_paginated_and_scoped_to_user(aws):
    first = create()[1]["document"]["document_id"]
    second = create()[1]["document"]["document_id"]
    create(user="user-2")
    status, page = call(event("GET", "/documents", query={"limit": "1"}))
    assert status == 200
    assert len(page["documents"]) == 1
    assert page["next_cursor"]
    status, next_page = call(event("GET", "/documents", query={
        "limit": "1", "cursor": page["next_cursor"]
    }))
    assert status == 200
    assert {page["documents"][0]["document_id"], next_page["documents"][0]["document_id"]} == {first, second}
    assert call(event("GET", "/documents", user="user-2", query={
        "cursor": page["next_cursor"]
    })) == (400, {"error": "INVALID_CURSOR"})


def test_detail_ownership_and_result_serialization(aws):
    doc_id = create()[1]["document"]["document_id"]
    aws.update_item(
        Key={"PK": "USER#user-1", "SK": f"DOC#{doc_id}"},
        UpdateExpression="SET #s=:s, confidence=:c, extracted=:e, warnings=:w",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "SUCCEEDED", ":c": api.Decimal("96.5"),
            ":e": {"total_amount": api.Decimal("450000")}, ":w": [],
        },
    )
    status, body = call(event("GET", f"/documents/{doc_id}", doc_id=doc_id))
    assert status == 200
    assert body["document"]["confidence"] == 96.5
    assert body["document"]["extracted"]["total_amount"] == 450000
    assert "s3_key" not in body["document"]
    assert call(event("GET", f"/documents/{doc_id}", user="user-2", doc_id=doc_id)) == (
        404, {"error": "NOT_FOUND"}
    )


def test_detail_normalises_tv4_json_strings_without_expanding_list(aws):
    doc_id = create()[1]["document"]["document_id"]
    aws.update_item(
        Key={"PK": "USER#user-1", "SK": f"DOC#{doc_id}"},
        UpdateExpression="SET #s=:s, extracted=:e, warnings=:w",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "NEEDS_REVIEW",
            ":e": json.dumps({"vendor_name": "Demo"}),
            ":w": json.dumps([{"code": "LOW_CONFIDENCE", "message": "Kiểm tra tổng tiền"}]),
        },
    )
    detail = call(event("GET", f"/documents/{doc_id}", doc_id=doc_id))[1]["document"]
    assert detail["extracted"] == {"vendor_name": "Demo"}
    assert detail["warnings"][0]["code"] == "LOW_CONFIDENCE"
    listing = call(event("GET", "/documents"))[1]["documents"][0]
    assert "extracted" not in listing and "warnings" not in listing


def test_bad_json_limit_and_cursor(aws):
    request = event("POST", "/documents")
    request["body"] = "{"
    assert call(request) == (400, {"error": "INVALID_JSON"})
    assert call(event("GET", "/documents", query={"limit": "101"})) == (
        400, {"error": "INVALID_LIMIT"}
    )
    assert call(event("GET", "/documents", query={"cursor": "!!!"})) == (
        400, {"error": "INVALID_CURSOR"}
    )
