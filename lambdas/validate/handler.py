"""Lambda Validate Skeleton

Phụ trách chính: TV2 (Ingestion & Queue)
Vai trò:
- Nhận thông báo S3 Event khi người dùng upload file mới.
- Kiểm tra tính hợp lệ của file (định dạng PDF/JPG/PNG, dung lượng < 10MB).
- Đẩy metadata vào SQS Processing Queue nếu hợp lệ, hoặc Dead Letter Queue nếu lỗi.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info("Lambda Validate received event: %s", json.dumps(event))

    # TODO (TV2): Tích hợp logic kiểm tra file và gửi SQS thật
    records = event.get("Records", [])
    logger.info("Found %d record(s) to validate", len(records))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Lambda Validate skeleton executed successfully",
            "processed_records": len(records)
        })
    }
