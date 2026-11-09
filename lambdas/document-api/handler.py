"""Authenticated document API for API Gateway HTTP API (payload format 2.0)."""

import base64
import binascii
import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger(__name__)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
PUBLIC_FIELDS = (
    "document_id", "document_type", "file_name", "status", "created_at",
    "updated_at", "reject_reason", "confidence", "warnings", "extracted",
)


class RequestError(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(payload, ensure_ascii=False, default=_json_default),
    }


def _claims(event):
    claims = (event.get("requestContext", {}).get("authorizer", {})
              .get("jwt", {}).get("claims", {}))
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not ID_RE.fullmatch(user_id):
        raise RequestError(401, "UNAUTHORIZED")
    return user_id


def _body(event):
    if event.get("isBase64Encoded"):
        raise RequestError(400, "INVALID_JSON")
    raw = event.get("body") or ""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 8192:
        raise RequestError(400, "INVALID_JSON")
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise RequestError(400, "INVALID_JSON") from None
    if not isinstance(body, dict):
        raise RequestError(400, "INVALID_JSON")
    return body


def _upload_input(body):
    if set(body) != {"file_name", "document_type", "content_type"}:
        raise RequestError(400, "INVALID_INPUT")
    name = body["file_name"]
    if (not isinstance(name, str) or not name or len(name) > 255
            or "/" in name or "\\" in name
            or any(unicodedata.category(char).startswith("C") for char in name)):
        raise RequestError(400, "INVALID_FILE_NAME")
    extension = os.path.splitext(name)[1].lower()
    if extension not in CONTENT_TYPES or body["content_type"] != CONTENT_TYPES[extension]:
        raise RequestError(400, "UNSUPPORTED_FILE_TYPE")
    if body["document_type"] not in ("INVOICE", "TRANSCRIPT"):
        raise RequestError(400, "INVALID_DOCUMENT_TYPE")
    return name, body["document_type"], body["content_type"]


def _cursor(value, user_id):
    if not value:
        return None
    if not isinstance(value, str) or len(value) > 1024:
        raise RequestError(400, "INVALID_CURSOR")
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
        raise RequestError(400, "INVALID_CURSOR") from None
    if (not isinstance(data, dict) or set(data) != {"PK", "SK"}
            or data["PK"] != f"USER#{user_id}"
            or not isinstance(data["SK"], str)
            or not data["SK"].startswith("DOC#")):
        raise RequestError(400, "INVALID_CURSOR")
    return data


def _public(item):
    return {field: item[field] for field in PUBLIC_FIELDS if field in item}


def _table():
    return boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"])


def _create(event, user_id):
    name, doc_type, content_type = _upload_input(_body(event))
    document_id = str(uuid.uuid4())
    key = f"uploads/{user_id}/{document_id}/{name}"
    if len(key.encode("utf-8")) > 1024:
        raise RequestError(400, "INVALID_FILE_NAME")
    bucket = os.environ["UPLOAD_BUCKET"]
    params = {
        "Bucket": bucket, "Key": key, "ContentType": content_type,
        "IfNoneMatch": "*",
    }
    url = boto3.client("s3", config=Config(signature_version="s3v4")).generate_presigned_url(
        "put_object", Params=params, ExpiresIn=900, HttpMethod="PUT"
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    item = {
        "PK": f"USER#{user_id}", "SK": f"DOC#{document_id}",
        "user_id": user_id, "document_id": document_id,
        "file_name": name, "document_type": doc_type, "s3_key": key,
        "status": "UPLOAD_PENDING", "created_at": now, "updated_at": now,
    }
    _table().put_item(
        Item=item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"
    )
    return _response(201, {
        "document": _public(item), "upload_url": url,
        "upload_method": "PUT",
        "upload_headers": {"Content-Type": content_type, "If-None-Match": "*"},
        "expires_in": 900,
    })


def _list(event, user_id):
    query = event.get("queryStringParameters") or {}
    try:
        limit = int(query.get("limit", "20"))
    except (ValueError, TypeError):
        raise RequestError(400, "INVALID_LIMIT") from None
    if not 1 <= limit <= 100:
        raise RequestError(400, "INVALID_LIMIT")
    params = {
        "KeyConditionExpression": Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("DOC#"),
        "Limit": limit,
        "ScanIndexForward": False,
    }
    cursor = _cursor(query.get("cursor"), user_id)
    if cursor:
        params["ExclusiveStartKey"] = cursor
    result = _table().query(**params)
    next_key = result.get("LastEvaluatedKey")
    next_cursor = None
    if next_key:
        encoded = base64.urlsafe_b64encode(
            json.dumps({"PK": next_key["PK"], "SK": next_key["SK"]}).encode()
        )
        next_cursor = encoded.decode().rstrip("=")
    return _response(200, {
        "documents": [_public(item) for item in result.get("Items", [])],
        "next_cursor": next_cursor,
    })


def _detail(event, user_id):
    doc_id = (event.get("pathParameters") or {}).get("document_id")
    if not isinstance(doc_id, str) or not ID_RE.fullmatch(doc_id):
        raise RequestError(404, "NOT_FOUND")
    result = _table().get_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"},
        ConsistentRead=True,
    )
    if "Item" not in result:
        raise RequestError(404, "NOT_FOUND")
    return _response(200, {"document": _public(result["Item"])})


def lambda_handler(event, _context):
    try:
        user_id = _claims(event)
        method = event.get("requestContext", {}).get("http", {}).get("method")
        path = event.get("rawPath", "")
        if method == "POST" and path == "/documents":
            return _create(event, user_id)
        if method == "GET" and path == "/documents":
            return _list(event, user_id)
        if method == "GET" and path.startswith("/documents/"):
            return _detail(event, user_id)
        raise RequestError(404, "NOT_FOUND")
    except RequestError as error:
        return _response(error.status, {"error": error.code})
    except (BotoCoreError, ClientError, KeyError) as error:
        request_id = event.get("requestContext", {}).get("requestId", "unknown")
        LOGGER.error("Document API dependency failure type=%s request_id=%s",
                     type(error).__name__, request_id)
        return _response(500, {"error": "INTERNAL_ERROR"})
