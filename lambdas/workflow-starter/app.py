"""Nhận SQS Processing Queue và khởi động Standard Step Functions."""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
INPUT_FIELDS = (
    "schema_version", "document_id", "user_id", "document_type",
    "bucket", "key", "file_name", "content_type", "size_bytes", "etag", "attempt",
)
REQUIRED_FIELDS = set(INPUT_FIELDS) | {"request_id", "queued_at"}
FINISHED_OR_RUNNING = {"PROCESSING", "SUCCEEDED", "NEEDS_REVIEW", "FAILED"}
NAMESPACE = "IDP/Ingestion"
CONTENT_TYPES = {
    ".pdf": "application/pdf", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".png": "image/png",
}


class NotReadyError(RuntimeError):
    """Validate chưa ghi QUEUED; SQS sẽ giao message lại."""


@dataclass
class Dependencies:
    table: Any
    sfn: Any
    state_machine_arn: str
    upload_bucket: str
    upload_prefix: str = "uploads/"


_deps = None


def get_dependencies() -> Dependencies:
    global _deps
    if _deps is None:
        _deps = Dependencies(
            table=boto3.resource("dynamodb").Table(os.environ["DOCUMENTS_TABLE"]),
            sfn=boto3.client("stepfunctions"),
            state_machine_arn=os.environ["STATE_MACHINE_ARN"],
            upload_bucket=os.environ["UPLOAD_BUCKET"],
            upload_prefix=os.environ.get("UPLOAD_PREFIX", "uploads/"),
        )
    return _deps


def emit_metric(name: str) -> None:
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [[]],
                "Metrics": [{"Name": name, "Unit": "Count"}],
            }],
        },
        name: 1,
    }))


def parse_message(body: str, deps: Dependencies) -> dict:
    msg = json.loads(body)
    if not isinstance(msg, dict) or not REQUIRED_FIELDS <= msg.keys():
        raise ValueError("Sai cấu trúc message 1.0")
    if msg["schema_version"] != "1.0":
        raise ValueError("Không hỗ trợ schema_version")
    if not all(isinstance(msg[k], str) and ID_RE.fullmatch(msg[k]) for k in ("user_id", "document_id")):
        raise ValueError("user_id/document_id không hợp lệ")
    if msg["document_type"] not in ("INVOICE", "TRANSCRIPT"):
        raise ValueError("document_type không hợp lệ")
    if type(msg["attempt"]) is not int or msg["attempt"] != 1:
        raise ValueError("Chỉ hỗ trợ attempt=1; reprocess cần contract riêng")
    if type(msg["size_bytes"]) is not int or msg["size_bytes"] <= 0:
        raise ValueError("size_bytes không hợp lệ")
    if (not isinstance(msg["file_name"], str) or not msg["file_name"]
            or len(msg["file_name"]) > 255 or "/" in msg["file_name"]
            or "\\" in msg["file_name"]
            or any(ord(c) < 32 or ord(c) == 127 for c in msg["file_name"])):
        raise ValueError("file_name không hợp lệ")
    # Match Validate's last-dot rule, including names such as .pdf and ..PDF.
    dot = msg["file_name"].rfind(".")
    suffix = msg["file_name"][dot:].lower() if dot != -1 else ""
    if suffix not in CONTENT_TYPES or msg["content_type"] != CONTENT_TYPES[suffix]:
        raise ValueError("content_type không khớp định dạng đã hỗ trợ")
    if not isinstance(msg["etag"], str) or not msg["etag"] or len(msg["etag"]) > 128:
        raise ValueError("etag không hợp lệ")
    expected_key = f'{deps.upload_prefix}{msg["user_id"]}/{msg["document_id"]}/{msg["file_name"]}'
    if msg["bucket"] != deps.upload_bucket or msg["key"] != expected_key or not msg["etag"]:
        raise ValueError("bucket/key/etag không khớp")
    return msg


def execution_name(msg: dict) -> str:
    identity = json.dumps(
        [msg["user_id"], msg["document_id"], msg["attempt"]], separators=(",", ":")
    ).encode("utf-8")
    return "doc-" + hashlib.sha256(identity).hexdigest()[:32]


def execution_arn(state_machine_arn: str, name: str) -> str:
    parts = state_machine_arn.split(":")
    if (len(parts) not in (7, 8) or parts[0] != "arn" or parts[2] != "states"
            or parts[5] != "stateMachine" or not parts[6] or "/" in parts[6]):
        raise ValueError("STATE_MACHINE_ARN không hợp lệ")
    return ":".join(parts[:5] + ["execution", parts[6], name])


def verify_existing(deps: Dependencies, name: str, input_json: str) -> None:
    old = deps.sfn.describe_execution(
        executionArn=execution_arn(deps.state_machine_arn, name)
    )
    if json.loads(old["input"]) != json.loads(input_json):
        raise RuntimeError("Execution cùng tên nhưng khác input; cần điều tra")


def process_message(body: str, deps: Dependencies) -> str:
    msg = parse_message(body, deps)
    doc = deps.table.get_item(
        Key={"PK": f'USER#{msg["user_id"]}', "SK": f'DOC#{msg["document_id"]}'},
        ConsistentRead=True,
    ).get("Item")
    if doc is None or doc.get("status") == "UPLOAD_PENDING":
        raise NotReadyError("Documents chưa QUEUED")
    if doc.get("status") not in ({"QUEUED"} | FINISHED_OR_RUNNING):
        raise RuntimeError("Documents có trạng thái không phù hợp")
    for field, expected in (
        ("document_type", msg["document_type"]),
        ("file_name", msg["file_name"]),
        ("s3_key", msg["key"]),
        ("object_etag", msg["etag"]),
        ("size_bytes", msg["size_bytes"]),
    ):
        if doc.get(field) != expected:
            raise RuntimeError(f"Documents khác message ở trường {field}")

    input_json = json.dumps(
        {key: msg[key] for key in INPUT_FIELDS},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    name = execution_name(msg)
    if doc["status"] != "QUEUED":
        verify_existing(deps, name, input_json)
        return "DUPLICATE"
    try:
        deps.sfn.start_execution(
            stateMachineArn=deps.state_machine_arn, name=name, input=input_json
        )
        return "STARTED"
    except ClientError as err:
        if err.response["Error"]["Code"] != "ExecutionAlreadyExists":
            raise
        verify_existing(deps, name, input_json)
        return "DUPLICATE"


def lambda_handler(event, context):
    deps = get_dependencies()
    failures = []
    for record in event.get("Records", []):
        try:
            outcome = process_message(record["body"], deps)
            print(json.dumps({
                "event": "starter_done", "message_id": record["messageId"],
                "document_id": json.loads(record["body"])["document_id"], "outcome": outcome,
                "request_id": getattr(context, "aws_request_id", "local"),
            }))
            emit_metric("WorkflowStarted" if outcome == "STARTED" else "WorkflowDuplicate")
        except Exception as err:
            retry = isinstance(err, NotReadyError)
            emit_metric("StarterRecordRetry" if retry else "StarterRecordFailed")
            print(json.dumps({
                "event": "starter_record_failed", "message_id": record["messageId"],
                "error_type": type(err).__name__,
                "request_id": getattr(context, "aws_request_id", "local"),
            }))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
