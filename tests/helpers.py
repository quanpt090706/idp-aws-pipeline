"""Hàm dựng dữ liệu giả dùng chung cho các test."""
from urllib.parse import quote_plus

PDF_BYTES = b"%PDF-1.7\n%fake pdf body for tests\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def make_s3_event(bucket: str, key: str, size: int = 1234, event_name: str = "ObjectCreated:Put", etag: str = "abc123") -> dict:
    """Event giống hệt S3 gửi cho Lambda (key được URL-encode như thật)."""
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "eventName": event_name,
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": quote_plus(key, safe="/"), "size": size, "eTag": etag},
                },
            }
        ]
    }


def make_sqs_record(body: str, message_id: str = "m-1") -> dict:
    return {"messageId": message_id, "body": body}
