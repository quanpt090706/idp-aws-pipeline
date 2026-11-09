"""Cấu hình của Lambda Validate, đọc từ biến môi trường (Terraform của TV5 sẽ set)."""
import os
from dataclasses import dataclass

DEFAULT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB = giới hạn JPEG/PNG của Textract
DEFAULT_UPLOAD_PREFIX = "uploads/"


@dataclass(frozen=True)
class Settings:
    documents_table: str
    queue_url: str
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    upload_prefix: str = DEFAULT_UPLOAD_PREFIX
    upload_bucket: str | None = None

    def __post_init__(self):
        if not self.documents_table or not self.queue_url:
            raise ValueError("DOCUMENTS_TABLE/QUEUE_URL must not be empty")
        if self.max_file_size_bytes <= 0:
            raise ValueError("MAX_FILE_SIZE_BYTES must be positive")
        if not self.upload_prefix or not self.upload_prefix.endswith("/"):
            raise ValueError("UPLOAD_PREFIX must end with /")


def load_settings(env=None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        documents_table=env["DOCUMENTS_TABLE"],
        queue_url=env["QUEUE_URL"],
        max_file_size_bytes=int(env.get("MAX_FILE_SIZE_BYTES", DEFAULT_MAX_FILE_SIZE_BYTES)),
        upload_prefix=env.get("UPLOAD_PREFIX", DEFAULT_UPLOAD_PREFIX),
        upload_bucket=env.get("UPLOAD_BUCKET"),
    )
