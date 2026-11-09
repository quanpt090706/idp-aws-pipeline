"""Lambda Parse Skeleton

Phụ trách chính: TV3 (Core OCR / AI)
Vai trò:
- Nhận thông báo hoàn tất từ SNS Topic (kèm JobId).
- Gọi GetDocumentAnalysis / GetExpenseAnalysis để lấy toàn bộ JSON Blocks từ Textract.
- Trích xuất dữ liệu có cấu trúc:
  + Hóa đơn: vendor, date, total, invoice_no, items.
  + Bảng điểm: student_name, student_id, subjects, scores.
- Lưu raw JSON vào S3 Results và lưu structured data vào DynamoDB Documents.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info("Lambda Parse received event: %s", json.dumps(event))

    # TODO (TV3): Tích hợp hàm parser bóc tách Blocks JSON từ Textract
    # và cập nhật trạng thái SUCCEEDED vào DynamoDB
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Lambda Parse skeleton executed successfully",
            "status": "SUCCEEDED"
        })
    }
