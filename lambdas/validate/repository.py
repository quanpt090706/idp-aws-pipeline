"""Truy cập DynamoDB (bảng Documents). TV2 CHỈ được đổi: UPLOAD_PENDING -> QUEUED | REJECTED.

Key theo docs/data-model.md: PK = USER#<user_id>, SK = DOC#<document_id>.
Nếu TV4 đổi key schema, chỉ cần sửa hàm `key()` ở đây.
"""
from typing import Optional

from botocore.exceptions import ClientError

STATUS_UPLOAD_PENDING = "UPLOAD_PENDING"
STATUS_QUEUED = "QUEUED"
STATUS_REJECTED = "REJECTED"


class DocumentRepository:
    def __init__(self, table):
        self._table = table

    @staticmethod
    def key(user_id: str, document_id: str) -> dict:
        return {"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"}

    def get(self, user_id: str, document_id: str) -> Optional[dict]:
        resp = self._table.get_item(Key=self.key(user_id, document_id), ConsistentRead=True)
        return resp.get("Item")

    def mark_queued(self, user_id: str, document_id: str, *, size_bytes: int, content_type: str, s3_key: str, etag: str, now: str) -> bool:
        return self._transition(
            user_id,
            document_id,
            update="SET #s = :new, size_bytes = :size, content_type = :ct, s3_key = :key, object_etag = :etag, queued_at = :now, updated_at = :now",
            values={":new": STATUS_QUEUED, ":size": size_bytes, ":ct": content_type, ":key": s3_key, ":etag": etag, ":now": now},
        )

    def mark_rejected(self, user_id: str, document_id: str, *, reason: str, detail: str, now: str) -> bool:
        return self._transition(
            user_id,
            document_id,
            update="SET #s = :new, reject_reason = :r, reject_detail = :d, rejected_at = :now, updated_at = :now",
            values={":new": STATUS_REJECTED, ":r": reason, ":d": detail, ":now": now},
        )

    def _transition(self, user_id: str, document_id: str, *, update: str, values: dict) -> bool:
        """Chuyển trạng thái CÓ ĐIỀU KIỆN. Trả False nếu document không còn ở UPLOAD_PENDING
        (tức là event trùng, hoặc đã có ai đó xử lý) - đây KHÔNG phải lỗi."""
        try:
            self._table.update_item(
                Key=self.key(user_id, document_id),
                UpdateExpression=update,
                ConditionExpression="#s = :pending",
                ExpressionAttributeNames={"#s": "status"},  # 'status' là từ khóa dành riêng của DynamoDB
                ExpressionAttributeValues={**values, ":pending": STATUS_UPLOAD_PENDING},
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
