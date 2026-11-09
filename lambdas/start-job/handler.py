"""Lambda Start-Job Skeleton

Phụ trách chính: TV3 (Core OCR / AI)
Vai trò:
- Nhận input từ Step Functions (s3_bucket, s3_key, document_id, document_type).
- Khởi động Textract Async Job (StartExpenseAnalysis cho hóa đơn hoặc StartDocumentAnalysis cho bảng điểm).
- Đăng ký SNS Topic để nhận callback khi job hoàn tất.
- Trả về JobId cho Step Functions tiếp tục chuyển trạng thái chờ.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info("Lambda Start-Job received event: %s", json.dumps(event))

    document_id = event.get("document_id", "doc-mock-001")
    document_type = event.get("document_type", "INVOICE")
    s3_key = event.get("s3_key", "")

    logger.info("Starting Textract async job for doc: %s, type: %s, key: %s", document_id, document_type, s3_key)

    # TODO (TV3): Tích hợp boto3 Textract:
    # response = textract.start_expense_analysis(...) / start_document_analysis(...)
    mock_job_id = f"job-{document_id}-mock-textract-id"

    return {
        "statusCode": 200,
        "job_id": mock_job_id,
        "document_id": document_id,
        "document_type": document_type,
        "status": "PROCESSING"
    }
