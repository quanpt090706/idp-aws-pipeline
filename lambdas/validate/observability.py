"""Log JSON có cấu trúc + metric CloudWatch (Embedded Metric Format).

Quy tắc: KHÔNG log token, presigned URL, tên file, S3 key (có thể chứa PII).
Chỉ log document_id, user_id, request_id, kích thước, lý do.
"""
import json
import time

NAMESPACE = "IDP/Ingestion"


def log(event: str, level: str = "INFO", **fields) -> None:
    print(json.dumps({"level": level, "event": event, **fields}, default=str, ensure_ascii=False))


def metric(name: str, value: float = 1, unit: str = "Count", **dimensions) -> None:
    """In 1 dòng EMF; CloudWatch tự tạo metric từ dòng log này (không cần gọi API)."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": NAMESPACE,
                            "Dimensions": [list(dimensions)] if dimensions else [[]],
                            "Metrics": [{"Name": name, "Unit": unit}],
                        }
                    ],
                },
                name: value,
                **dimensions,
            }
        )
    )
