#!/usr/bin/env python3
"""Run one intentional Stage 4 write test against the shared AWS dev stack.

This bypasses TV1/TV2 so a team can verify TV3 + TV4 independently:
S3 object -> Step Functions -> StartJob -> Textract -> SNS -> Parse -> result.
The command refuses to write unless --confirm-dev-write is supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3


ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
TERMINAL_EXECUTION_STATUSES = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}


def content_type_for(path: Path) -> str:
    content_type = CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        raise ValueError("Chỉ hỗ trợ PDF, JPG, JPEG hoặc PNG.")
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("File test không tồn tại hoặc rỗng.")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("File test vượt quá 10 MiB.")
    return content_type


def execution_name(user_id: str, document_id: str, attempt: int = 1) -> str:
    identity = json.dumps(
        [user_id, document_id, attempt], separators=(",", ":")
    ).encode("utf-8")
    return "doc-" + hashlib.sha256(identity).hexdigest()[:32]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_execution_input(
    *,
    document_id: str,
    user_id: str,
    document_type: str,
    bucket: str,
    key: str,
    file_name: str,
    content_type: str,
    size_bytes: int,
    etag: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document_id": document_id,
        "user_id": user_id,
        "document_type": document_type,
        "bucket": bucket,
        "key": key,
        "file_name": file_name,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "etag": etag,
        "attempt": 1,
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload one sample and verify the real TV3 Textract callback flow."
    )
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument(
        "--document-type", required=True, choices=("INVOICE", "TRANSCRIPT")
    )
    parser.add_argument("--upload-bucket", required=True)
    parser.add_argument("--results-bucket", required=True)
    parser.add_argument("--documents-table", required=True)
    parser.add_argument("--state-machine-arn", required=True)
    parser.add_argument("--user-id", default="tv3-smoke-user")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--confirm-dev-write", action="store_true")
    return parser.parse_args()


def _decode_attribute(value: dict[str, Any]) -> Any:
    if "S" in value:
        candidate = value["S"]
        if isinstance(candidate, str) and candidate[:1] in "[{":
            try:
                return json.loads(candidate)
            except ValueError:
                pass
        return candidate
    if "N" in value:
        number = float(value["N"])
        return int(number) if number.is_integer() else number
    if "BOOL" in value:
        return bool(value["BOOL"])
    if "NULL" in value:
        return None
    return value


def main() -> int:
    args = _args()
    if not args.confirm_dev_write:
        raise SystemExit(
            "Lệnh này ghi dữ liệu lên AWS dev. Chạy lại với --confirm-dev-write "
            "sau khi kiểm tra đúng account, region và resource names."
        )
    if not ID_RE.fullmatch(args.user_id):
        raise SystemExit("--user-id chỉ được chứa chữ, số, _ hoặc -, tối đa 64 ký tự.")
    if args.timeout_seconds < 30:
        raise SystemExit("--timeout-seconds phải ít nhất 30 giây.")

    sample = args.file.resolve()
    content_type = content_type_for(sample)
    document_id = str(uuid.uuid4())
    file_name = sample.name
    key = f"uploads/{args.user_id}/{document_id}/{file_name}"
    now = utc_now()

    session_args = {"region_name": args.region}
    if args.profile:
        session_args["profile_name"] = args.profile
    session = boto3.Session(**session_args)
    sts = session.client("sts")
    s3 = session.client("s3")
    dynamodb = session.client("dynamodb")
    stepfunctions = session.client("stepfunctions")

    identity = sts.get_caller_identity()
    print(
        json.dumps(
            {
                "event": "identity_confirmed",
                "account": identity["Account"],
                "arn": identity["Arn"],
                "region": args.region,
            },
            ensure_ascii=False,
        )
    )

    # Mark QUEUED before uploading so a configured TV2 S3 trigger treats its
    # event as a harmless duplicate instead of starting a second execution.
    dynamodb.put_item(
        TableName=args.documents_table,
        Item={
            "PK": {"S": f"USER#{args.user_id}"},
            "SK": {"S": f"DOC#{document_id}"},
            "user_id": {"S": args.user_id},
            "document_id": {"S": document_id},
            "document_type": {"S": args.document_type},
            "file_name": {"S": file_name},
            "s3_key": {"S": key},
            "status": {"S": "QUEUED"},
            "created_at": {"S": now},
            "updated_at": {"S": now},
        },
        ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
    )

    with sample.open("rb") as body:
        put_result = s3.put_object(
            Bucket=args.upload_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
    etag = str(put_result["ETag"]).strip('"')
    size_bytes = sample.stat().st_size

    execution_input = build_execution_input(
        document_id=document_id,
        user_id=args.user_id,
        document_type=args.document_type,
        bucket=args.upload_bucket,
        key=key,
        file_name=file_name,
        content_type=content_type,
        size_bytes=size_bytes,
        etag=etag,
    )
    started = stepfunctions.start_execution(
        stateMachineArn=args.state_machine_arn,
        name=execution_name(args.user_id, document_id),
        input=json.dumps(
            execution_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    execution_arn = started["executionArn"]
    print(
        json.dumps(
            {
                "event": "stage4_smoke_started",
                "document_id": document_id,
                "s3_key": key,
                "execution_arn": execution_arn,
            },
            ensure_ascii=False,
        )
    )

    deadline = time.monotonic() + args.timeout_seconds
    execution: dict[str, Any] = {}
    while time.monotonic() < deadline:
        execution = stepfunctions.describe_execution(executionArn=execution_arn)
        if execution["status"] in TERMINAL_EXECUTION_STATUSES:
            break
        time.sleep(5)
    else:
        raise TimeoutError(
            f"Execution chưa kết thúc sau {args.timeout_seconds} giây: {execution_arn}"
        )

    item_result = dynamodb.get_item(
        TableName=args.documents_table,
        Key={
            "PK": {"S": f"USER#{args.user_id}"},
            "SK": {"S": f"DOC#{document_id}"},
        },
        ConsistentRead=True,
    )
    item = {
        name: _decode_attribute(value)
        for name, value in item_result.get("Item", {}).items()
    }
    result_key = item.get("s3_result_key")
    raw_result_exists = False
    if isinstance(result_key, str) and result_key:
        s3.head_object(Bucket=args.results_bucket, Key=result_key)
        raw_result_exists = True

    summary = {
        "event": "stage4_smoke_finished",
        "execution_status": execution.get("status"),
        "document_id": document_id,
        "document_status": item.get("status"),
        "confidence": item.get("confidence"),
        "s3_result_key": result_key,
        "raw_result_exists": raw_result_exists,
        "extracted": item.get("extracted"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    passed = (
        execution.get("status") == "SUCCEEDED"
        and item.get("status") in {"SUCCEEDED", "NEEDS_REVIEW"}
        and raw_result_exists
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
