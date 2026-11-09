"""Lambda Validate (TV2). Trigger: S3 ObjectCreated trên bucket Upload.

Luồng cho mỗi object:
  parse key -> đọc record Documents -> (trùng? bỏ qua) -> kiểm tra file
     -> không hợp lệ: REJECTED (+ lý do)
      -> hợp lệ: gửi SQS rồi mới QUEUED; Starter retry nếu SQS đến trước khi thấy QUEUED
"""
from dataclasses import dataclass
from typing import Any

import boto3

import messages
import rules
from config import Settings, load_settings
from observability import log, metric
from repository import STATUS_UPLOAD_PENDING, DocumentRepository
from s3_event import InvalidKeyError, S3Object, parse_s3_event, parse_upload_key

# Kết quả xử lý 1 object (dùng cho log và test)
QUEUED = "QUEUED"
REJECTED = "REJECTED"
DUPLICATE = "DUPLICATE"


class MissingDocumentError(RuntimeError):
    """Có file trong S3 nhưng không có record Documents. Thử lại có thể hết lỗi (độ trễ ghi),
    nếu vẫn lỗi thì event vào failure destination để không bị mất."""


class ValidateProcessingError(RuntimeError):
    """Sanitized exception for Lambda's automatic traceback/error destination."""


@dataclass
class Dependencies:
    settings: Settings
    s3: Any
    sqs: Any
    repo: DocumentRepository


_deps = None


def get_dependencies() -> Dependencies:
    """Tạo client 1 lần mỗi cold start rồi tái sử dụng."""
    global _deps
    if _deps is None:
        settings = load_settings()
        table = boto3.resource("dynamodb").Table(settings.documents_table)
        _deps = Dependencies(settings, boto3.client("s3"), boto3.client("sqs"), DocumentRepository(table))
    return _deps


def fetch_header(s3, bucket: str, key: str, size: int, etag: str) -> bytes:
    """Đối chiếu event với object hiện tại; không đọc toàn bộ file."""
    if not etag:
        raise ValueError("S3 event thiếu eTag")
    meta = s3.head_object(Bucket=bucket, Key=key)
    if meta["ContentLength"] != size or meta["ETag"].strip('"') != etag:
        raise RuntimeError("Object đã thay đổi so với S3 event; kiểm tra ghi đè/key")
    resp = s3.get_object(
        Bucket=bucket, Key=key, Range=f"bytes=0-{rules.HEADER_BYTES - 1}", IfMatch=etag
    )
    body = resp["Body"]
    try:
        return body.read()
    finally:
        body.close()


def process_object(obj: S3Object, deps: Dependencies, request_id: str) -> str:
    cfg = deps.settings
    if cfg.upload_bucket and obj.bucket != cfg.upload_bucket:
        metric("UploadKeyMismatch")
        raise ValueError("Event bucket does not match UPLOAD_BUCKET")

    # 1) Tách user_id / document_id / file_name từ key
    try:
        parsed = parse_upload_key(obj.key, cfg.upload_prefix)
    except InvalidKeyError as err:
        log("invalid_key", level="WARNING", request_id=request_id, reason=str(err))
        metric("InvalidKey")
        raise  # đưa vào validate-failures sau retry, không âm thầm bỏ qua object

    ctx = {"document_id": parsed.document_id, "user_id": parsed.user_id, "request_id": request_id}

    # 2) Đọc record do API của TV1 tạo sẵn (status = UPLOAD_PENDING)
    doc = deps.repo.get(parsed.user_id, parsed.document_id)
    if doc is None:
        log("missing_document_record", level="ERROR", **ctx)
        metric("MissingDocumentRecord")
        raise MissingDocumentError(parsed.document_id)
    if doc.get("file_name") != parsed.file_name or (doc.get("s3_key") and doc["s3_key"] != obj.key):
        log("upload_key_mismatch", level="ERROR", **ctx)
        metric("UploadKeyMismatch")
        raise RuntimeError("Object key không khớp record do TV1 tạo")

    # 3) Event trùng / đã xử lý rồi -> bỏ qua, KHÔNG phải lỗi
    if doc.get("status") != STATUS_UPLOAD_PENDING:
        log("duplicate_event", status=doc.get("status"), **ctx)
        metric("DuplicateEvent")
        return DUPLICATE

    # 4) Kiểm tra file
    result = rules.validate_document_type(doc.get("document_type"))
    if result.ok:
        result = rules.validate_basic(parsed.file_name, obj.size, cfg.max_file_size_bytes)
    if result.ok:  # HEAD + ranged GET chỉ khi các bước rẻ đã qua
        header = fetch_header(deps.s3, obj.bucket, obj.key, obj.size, obj.etag)
        result = rules.validate_content(parsed.file_name, header)

    now = messages.utc_now_iso()
    if not result.ok:
        changed = deps.repo.mark_rejected(
            parsed.user_id, parsed.document_id, reason=result.reason, detail=result.detail, now=now
        )
        log("document_rejected", level="WARNING", reason=result.reason, size=obj.size, changed=changed, **ctx)
        if changed:
            metric("DocumentRejected", Reason=result.reason)
        return REJECTED if changed else DUPLICATE

    # 5) Hợp lệ: GỬI SQS TRƯỚC...
    content_type = rules.content_type_for(parsed.file_name)
    message = messages.build_message(
        document_id=parsed.document_id,
        user_id=parsed.user_id,
        document_type=doc["document_type"],
        bucket=obj.bucket,
        key=obj.key,
        file_name=parsed.file_name,
        content_type=content_type,
        size_bytes=obj.size,
        etag=obj.etag,
        request_id=request_id,
        queued_at=now,
    )
    deps.sqs.send_message(
        QueueUrl=cfg.queue_url,
        MessageBody=messages.to_json(message),
        MessageAttributes={
            "document_type": {"DataType": "String", "StringValue": message["document_type"]},
            "document_id": {"DataType": "String", "StringValue": message["document_id"]},
        },
    )
    # ...RỒI MỚI đổi trạng thái. Nếu Lambda chết giữa 2 bước, lần retry sẽ gửi lại 1 message nữa;
    # Workflow Starter chờ QUEUED và chặn trùng bằng tên/input execution xác định.
    changed = deps.repo.mark_queued(
        parsed.user_id, parsed.document_id, size_bytes=obj.size, content_type=content_type,
        s3_key=obj.key, etag=obj.etag, now=now
    )
    log("document_queued", size=obj.size, changed=changed, **ctx)
    if changed:
        metric("DocumentQueued", DocumentType=message["document_type"])
    return QUEUED if changed else DUPLICATE


def lambda_handler(event, context):
    request_id = getattr(context, "aws_request_id", "local")
    try:
        deps = get_dependencies()
        outcomes = [process_object(obj, deps, request_id) for obj in parse_s3_event(event)]
    except Exception as error:
        # Unhandled SDK exceptions can include object keys in their messages.
        # Preserve async failure/retry, but do not expose that message in logs.
        log("validate_failed", level="ERROR", request_id=request_id, error_type=type(error).__name__)
        raise ValidateProcessingError("Validate failed; inspect request_id and the failure destination") from None
    log("batch_done", request_id=request_id, outcomes=outcomes)
    return {"outcomes": outcomes}
