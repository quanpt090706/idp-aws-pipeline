"""Đọc S3 event và tách S3 key theo quy ước: uploads/<user_id>/<document_id>/<file_name>."""
import re
from dataclasses import dataclass
from urllib.parse import unquote_plus

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # an toàn cho DynamoDB key và tên execution của Step Functions
_MAX_FILE_NAME_LEN = 255


class InvalidKeyError(ValueError):
    """S3 key không đúng quy ước -> không thể xác định document."""


@dataclass(frozen=True)
class S3Object:
    bucket: str
    key: str  # ĐÃ URL-decode
    size: int
    etag: str
    event_name: str


@dataclass(frozen=True)
class UploadKey:
    user_id: str
    document_id: str
    file_name: str


def parse_s3_event(event: dict) -> list[S3Object]:
    """Trả về danh sách object mới tạo. Bỏ qua s3:TestEvent và mọi event không phải ObjectCreated."""
    objects = []
    for record in (event or {}).get("Records", []):
        event_name = record.get("eventName", "")
        if not event_name.startswith("ObjectCreated:"):
            continue
        if record.get("eventSource") != "aws:s3":
            raise ValueError("ObjectCreated event must come from aws:s3")
        s3 = record["s3"]
        objects.append(
            S3Object(
                bucket=s3["bucket"]["name"],
                # S3 gửi key dạng URL-encoded: khoảng trắng -> '+', ký tự Unicode -> %XX
                key=unquote_plus(s3["object"]["key"]),
                size=int(s3["object"]["size"]),
                etag=s3["object"]["eTag"],
                event_name=event_name,
            )
        )
    return objects


def parse_upload_key(key: str, prefix: str = "uploads/") -> UploadKey:
    if not key.startswith(prefix):
        raise InvalidKeyError("key không nằm dưới prefix upload")
    parts = key[len(prefix):].split("/")
    if len(parts) != 3:
        raise InvalidKeyError("key phải có dạng <prefix><user_id>/<document_id>/<file_name>")
    user_id, document_id, file_name = parts
    if not _ID_RE.fullmatch(user_id) or not _ID_RE.fullmatch(document_id):
        raise InvalidKeyError("user_id/document_id chứa ký tự không hợp lệ")
    if (not file_name or len(file_name) > _MAX_FILE_NAME_LEN
            or "\\" in file_name or any(ord(c) < 32 or ord(c) == 127 for c in file_name)):
        raise InvalidKeyError("file_name rỗng hoặc quá dài")
    return UploadKey(user_id=user_id, document_id=document_id, file_name=file_name)
