"""Lambda Mock Worker giả lập Textract & Parser (TV3) phục vụ kiểm thử TV4."""
import json
import os
import time
from typing import Any, Dict

import boto3

# Dữ liệu trích xuất mẫu cho Hóa đơn (INVOICE)
MOCK_INVOICE_EXTRACTED = {
    "vendor": "Công ty Cổ phần Sữa Việt Nam (Vinamilk)",
    "invoice_date": "2024-01-10",
    "invoice_no": "HD-2024-00123",
    "total_amount": "15,400,000",
    "currency": "VND",
    "items": [
        {"description": "Sữa tươi tiệt trùng 100% 1L", "qty": "100", "unit_price": "30,000", "amount": "3,000,000"},
        {"description": "Sữa đặc có đường Ông Thọ", "qty": "240", "unit_price": "52,000", "amount": "12,400,000"}
    ]
}

# Dữ liệu trích xuất mẫu cho Bảng điểm (TRANSCRIPT)
MOCK_TRANSCRIPT_EXTRACTED = {
    "student_name": "Nguyen Van A",
    "student_id": "SV-2024-9999",
    "major": "Khoa học Máy tính",
    "gpa": "3.85",
    "subjects": [
        {"course_code": "CS301", "course_name": "Điện toán đám mây", "credits": "3", "grade": "A+"},
        {"course_code": "CS302", "course_name": "Cơ sở dữ liệu NoSQL", "credits": "3", "grade": "A"}
    ]
}


def build_mock_ocr_result(
    document_id: str,
    user_id: str,
    document_type: str,
    scenario: str = "SUCCEEDED"
) -> Dict[str, Any]:
    """Tạo payload kết quả OCR mẫu theo kịch bản."""
    s3_result_key = f"processed/{user_id}/2024/01/{document_id}.json"

    if scenario == "SUCCEEDED":
        extracted = MOCK_INVOICE_EXTRACTED if document_type == "INVOICE" else MOCK_TRANSCRIPT_EXTRACTED
        return {
            "status": "SUCCEEDED",
            "document_id": document_id,
            "document_type": document_type,
            "s3_result_key": s3_result_key,
            "confidence": 96.5,
            "extracted": extracted,
            "warnings": []
        }
    elif scenario == "NEEDS_REVIEW":
        return {
            "status": "NEEDS_REVIEW",
            "document_id": document_id,
            "document_type": document_type,
            "s3_result_key": s3_result_key,
            "confidence": 62.0,
            "extracted": {
                "vendor": "Không rõ tên nhà cung cấp",
                "total_amount": None,
                "items": []
            },
            "warnings": ["LOW_CONFIDENCE", "MISSING_TOTAL_AMOUNT", "BLURRY_IMAGE"]
        }
    else:
        return {
            "status": "FAILED",
            "document_id": document_id,
            "error_code": "TEXTRACT_UNREADABLE_FILE",
            "message": "File bị lỗi hoặc không thể nhận dạng văn bản"
        }


def save_job_callback(
    table_name: str,
    job_id: str,
    task_token: str,
    document_id: str,
    user_id: str,
    ttl_days: int = 7
) -> None:
    """Lưu ánh xạ job_id và task_token vào bảng JobCallbacks kèm TTL."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    expire_at = int(time.time()) + (ttl_days * 86400)

    table.put_item(
        Item={
            "job_id": job_id,
            "task_token": task_token,
            "document_id": document_id,
            "user_id": user_id,
            "ttl": expire_at,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
    )


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Handler giả lập việc TV3 nhận lệnh phân tích, lưu token và gửi kết quả callback lại cho Step Functions.
    """
    task_token = event.get("task_token")
    document_id = event.get("document_id")
    user_id = event.get("user_id")
    document_type = event.get("document_type", "INVOICE")
    scenario = event.get("mock_scenario", "SUCCEEDED")

    # Lưu token vào JobCallbacks nếu có cấu hình bảng
    job_callbacks_table = os.environ.get("JOB_CALLBACKS_TABLE")
    job_id = f"job-{document_id[:8]}"
    if job_callbacks_table and task_token:
        save_job_callback(job_callbacks_table, job_id, task_token, document_id, user_id)

    # Sinh kết quả giả lập
    result = build_mock_ocr_result(document_id, user_id, document_type, scenario)

    # Nếu có task_token, gửi callback về Step Functions
    sfn_client = boto3.client("stepfunctions")
    if task_token:
        if scenario in ("SUCCEEDED", "NEEDS_REVIEW"):
            sfn_client.send_task_success(
                taskToken=task_token,
                output=json.dumps(result, ensure_ascii=False)
            )
        else:
            sfn_client.send_task_failure(
                taskToken=task_token,
                error="TextractExecutionError",
                cause=json.dumps(result, ensure_ascii=False)
            )

    return result
