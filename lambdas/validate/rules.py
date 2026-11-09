"""Quy tắc chấp nhận / từ chối file. Hàm thuần (không gọi AWS) nên test rất dễ."""
from dataclasses import dataclass
from typing import Optional

# --- Quy tắc nghiệp vụ (chốt ở Giai đoạn 0) -------------------------------------------------
ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
ALLOWED_DOCUMENT_TYPES = {"INVOICE", "TRANSCRIPT"}
HEADER_BYTES = 16  # số byte đầu file cần đọc để kiểm tra "magic bytes"

# --- Mã lý do từ chối (lưu vào DynamoDB.reject_reason, UI map sang tiếng Việt) --------------
UNSUPPORTED_EXTENSION = "UNSUPPORTED_EXTENSION"
FILE_EMPTY = "FILE_EMPTY"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
CONTENT_MISMATCH = "CONTENT_MISMATCH"
INVALID_DOCUMENT_TYPE = "INVALID_DOCUMENT_TYPE"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: Optional[str] = None
    detail: Optional[str] = None


OK = ValidationResult(ok=True)


def get_extension(file_name: str) -> str:
    dot = file_name.rfind(".")
    return file_name[dot:].lower() if dot != -1 else ""


def content_type_for(file_name: str) -> Optional[str]:
    return ALLOWED_EXTENSIONS.get(get_extension(file_name))


def detect_format(header: bytes) -> Optional[str]:
    """Nhận diện định dạng thật từ byte đầu file (không tin đuôi file)."""
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def validate_document_type(document_type: Optional[str]) -> ValidationResult:
    if not isinstance(document_type, str) or document_type not in ALLOWED_DOCUMENT_TYPES:
        return ValidationResult(False, INVALID_DOCUMENT_TYPE, "document_type must be INVOICE or TRANSCRIPT")
    return OK


def validate_basic(file_name: str, size: int, max_size: int) -> ValidationResult:
    """Kiểm tra rẻ (không cần đọc file): đuôi file + kích thước."""
    ext = get_extension(file_name)
    if ext not in ALLOWED_EXTENSIONS:
        return ValidationResult(False, UNSUPPORTED_EXTENSION, f"extension={ext or '(none)'}")
    if size <= 0:
        return ValidationResult(False, FILE_EMPTY, "size=0")
    if size > max_size:
        return ValidationResult(False, FILE_TOO_LARGE, f"size={size} max={max_size}")
    return OK


def validate_content(file_name: str, header: bytes) -> ValidationResult:
    """Kiểm tra byte đầu file khớp với đuôi file (chặn file giả mạo / hỏng ngay từ đầu)."""
    expected = content_type_for(file_name)
    detected = detect_format(header)
    if detected is None or detected != expected:
        return ValidationResult(False, CONTENT_MISMATCH, f"expected={expected} detected={detected}")
    return OK
