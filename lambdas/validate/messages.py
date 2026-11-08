"""Message contract TV2 -> TV4 (Starter tạo input Step Functions ổn định từ SQS body)."""
import json
from datetime import datetime, timezone
from typing import Optional

SCHEMA_VERSION = "1.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_message(
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
    request_id: str,
    queued_at: Optional[str] = None,
    attempt: int = 1,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": document_id,
        "user_id": user_id,
        "document_type": document_type,  # INVOICE | TRANSCRIPT
        "bucket": bucket,
        "key": key,
        "file_name": file_name,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "etag": etag,
        "attempt": attempt,  # bản demo chỉ chấp nhận 1; reprocess cần contract riêng
        "request_id": request_id,  # request id của Lambda Validate, để truy vết log
        "queued_at": queued_at or utc_now_iso(),
    }


def to_json(message: dict) -> str:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    # S3 keys may contain these characters, but raw SQS bodies may not.
    # JSON escaping preserves the exact key after the consumer decodes it.
    return body.replace("\ufffe", "\\ufffe").replace("\uffff", "\\uffff")
