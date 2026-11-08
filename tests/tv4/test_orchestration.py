"""
Kiểm thử bộ phận của Thành viên 4 (Data & Orchestration):
1. Tính toàn vẹn cấu trúc State Machine ASL JSON, liên kết DAG và các cạnh chuyển tiếp của HandleFailure.
2. Vòng đời dữ liệu và cập nhật có điều kiện trong DynamoDB Single-Table (GSI-status, GSI-type).
3. Cơ chế Fencing Token / Ownership Locking chống Zombie Execution ghi đè dữ liệu.
4. Bảng phụ JobCallbacks và cơ chế TTL 7 ngày.
5. Lambda Mock Worker phản hồi cho các kịch bản SUCCEEDED, NEEDS_REVIEW, FAILED.
6. Lambda Notification gửi email qua Amazon SES:
   - Nested ocr_result payload & SUCCEEDED không có warnings.
   - Thân thiện hóa thông điệp lỗi (Sanitize error message).
   - Hiển thị đúng loại tài liệu (ngăn chặn mặc định sai thành Bảng điểm).
   - Bảo mật chống Header Injection & HTML Injection/XSS (cả Subject và Body).
   - Thứ tự ưu tiên người nhận (Sandbox -> Event -> DynamoDB -> Bỏ qua khi không có người nhận).
   - Bọc toàn bộ try/except tự phục hồi (Graceful Degradation).
"""
import html
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from mock_worker import (
    build_mock_ocr_result,
    lambda_handler as mock_worker_handler,
    save_job_callback,
)
from lambdas.notification.handler import (
    get_friendly_error_message,
    get_recipient_email,
    lambda_handler as notification_handler,
    render_email_content,
    sanitize_header_value,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
ASL_FILE = ROOT_DIR / "infra" / "step_functions" / "state_machine.asl.json"
FIXTURE_SFN_INPUT = ROOT_DIR / "tests" / "fixtures" / "step_functions_input.json"


# ==============================================================================
# 1. KIỂM THỬ CẤU TRÚC ASL JSON CỦA STATE MACHINE VÀ CÁC CẠNH CHUYỂN TIẾP
# ==============================================================================

def test_asl_json_syntax_and_structure():
    """Đảm bảo file ASL JSON hợp lệ, đầy đủ các State, không có liên kết treo (broken links)."""
    assert ASL_FILE.exists(), "Không tìm thấy file state_machine.asl.json"
    with open(ASL_FILE, "r", encoding="utf-8") as f:
        asl = json.load(f)

    assert asl["StartAt"] == "SetProcessingStatus"
    states = asl["States"]

    # 1. Kiểm tra toàn vẹn DAG và không có HeartbeatSeconds ở bất kỳ State nào
    for state_name, state_def in states.items():
        assert "HeartbeatSeconds" not in state_def, f"State {state_name} không được dùng HeartbeatSeconds vì Textract async không heartbeat!"
        if "Next" in state_def:
            assert state_def["Next"] in states, f"State {state_name} Next '{state_def['Next']}' không tồn tại!"
        if "Default" in state_def:
            assert state_def["Default"] in states, f"State {state_name} Default '{state_def['Default']}' không tồn tại!"
        if "Choices" in state_def:
            for choice in state_def["Choices"]:
                assert choice["Next"] in states, f"Choice trong {state_name} trỏ Next '{choice['Next']}' không tồn tại!"
        if "Catch" in state_def:
            for catch_block in state_def["Catch"]:
                assert catch_block["Next"] in states, f"Catch trong {state_name} trỏ Next '{catch_block['Next']}' không tồn tại!"

    # 1b. Kiểm tra mọi ErrorEquals DynamoDB đều phải khai báo đủ cả 2 cách viết DynamoDB. và DynamoDb.
    for state_name, state_def in states.items():
        handlers = []
        if "Retry" in state_def:
            handlers.extend(state_def["Retry"])
        if "Catch" in state_def:
            handlers.extend(state_def["Catch"])
        for h in handlers:
            err_list = h.get("ErrorEquals", [])
            for err in err_list:
                if err.startswith("DynamoDB."):
                    alt_err = err.replace("DynamoDB.", "DynamoDb.")
                    assert alt_err in err_list, f"State {state_name} có {err} nhưng thiếu cách viết {alt_err}"
                elif err.startswith("DynamoDb."):
                    alt_err = err.replace("DynamoDb.", "DynamoDB.")
                    assert alt_err in err_list, f"State {state_name} có {err} nhưng thiếu cách viết {alt_err}"

    # 2. Kiểm tra State SetProcessingStatus
    set_proc = states["SetProcessingStatus"]
    assert set_proc["Type"] == "Task"
    assert set_proc["Resource"] == "arn:aws:states:::dynamodb:updateItem"
    assert "attribute_exists(PK)" in set_proc["Parameters"]["ConditionExpression"]
    assert "#status = :queued OR (#status = :processing AND sfn_execution_id = :exec_id)" in set_proc["Parameters"]["ConditionExpression"]
    assert "sfn_execution_id = :exec_id" in set_proc["Parameters"]["UpdateExpression"]
    assert set_proc["Next"] == "RouteByDocumentType"
    assert any("DynamoDB.ConditionalCheckFailedException" in c["ErrorEquals"] for c in set_proc["Catch"])
    assert states["AlreadyProcessedNoOp"]["Type"] == "Pass"
    assert states["AlreadyProcessedNoOp"]["Next"] == "WorkflowSucceeded"

    # 3. Phân nhánh RouteByDocumentType
    router = states["RouteByDocumentType"]
    assert router["Type"] == "Choice"
    choices = {c["StringEquals"]: c["Next"] for c in router["Choices"]}
    assert choices.get("INVOICE") == "WaitForTextractInvoiceAnalysis"
    assert choices.get("TRANSCRIPT") == "WaitForTextractTranscriptAnalysis"
    assert router["Default"] == "HandleInvalidDocumentType"

    # 4. Phân loại kết quả EvaluateExtractionResult có kiểm tra IsPresent tránh States.Runtime
    eval_state = states["EvaluateExtractionResult"]
    assert eval_state["Type"] == "Choice"
    eval_targets = [c["Next"] for c in eval_state["Choices"]]
    assert "UpdateStatusSucceeded" in eval_targets
    assert "UpdateStatusNeedsReview" in eval_targets
    assert eval_state["Default"] == "HandleUnexpectedOcrStatus"
    assert states["HandleUnexpectedOcrStatus"]["Next"] == "HandleFailure"

    # 5. Kiểm tra đúng 3 cạnh của HandleFailure (Review mục 1)
    # - Next chính: trỏ tới SendFailureNotification
    # - Catch ConditionalCheckFailedException: trỏ về WorkflowFailed
    # - Catch States.ALL: trỏ về WorkflowFailed
    hf = states["HandleFailure"]
    assert hf["Type"] == "Task"
    assert hf["Next"] == "SendFailureNotification", "HandleFailure Next phải trỏ tới SendFailureNotification"
    hf_catch_targets = {tuple(c["ErrorEquals"]): c["Next"] for c in hf["Catch"]}
    # Cạnh Catch 1: Chặn ghi đè tài liệu đã xong
    assert any("DynamoDB.ConditionalCheckFailedException" in errs and target == "WorkflowFailed" for errs, target in hf_catch_targets.items())
    # Cạnh Catch 2: Lỗi khác
    assert any("States.ALL" in errs and target == "WorkflowFailed" for errs, target in hf_catch_targets.items())

    # 6. Kiểm tra SendCompletionNotification truyền nguyên ocr_result tránh lỗi thiếu warnings
    send_comp = states["SendCompletionNotification"]
    assert send_comp["Type"] == "Task"
    assert send_comp["Resource"] == "arn:aws:states:::lambda:invoke"
    assert send_comp["Parameters"]["FunctionName"] == "${NOTIFICATION_LAMBDA_ARN}"
    payload = send_comp["Parameters"]["Payload"]
    assert "ocr_result.$" in payload
    # Tuyệt đối không dùng JSONPath trỏ vào các trường tùy chọn của ocr_result
    assert "warnings.$" not in payload
    assert "summary.$" not in payload
    assert "extracted.$" not in payload
    assert send_comp["Next"] == "WorkflowSucceeded"
    assert any("States.ALL" in c["ErrorEquals"] and c["Next"] == "WorkflowSucceeded" for c in send_comp["Catch"])

    # 7. Kiểm tra SendFailureNotification
    send_fail = states["SendFailureNotification"]
    assert send_fail["Type"] == "Task"
    assert send_fail["Resource"] == "arn:aws:states:::lambda:invoke"
    assert send_fail["Parameters"]["FunctionName"] == "${NOTIFICATION_LAMBDA_ARN}"
    assert send_fail["Next"] == "WorkflowFailed"
    assert any("States.ALL" in c["ErrorEquals"] and c["Next"] == "WorkflowFailed" for c in send_fail["Catch"])


# ==============================================================================
# 2. KIỂM THỬ DYNAMODB SINGLE-TABLE LIFECYCLE & FENCING TOKEN
# ==============================================================================

@pytest.fixture
def dynamodb_tables():
    """Khởi tạo bảng Documents và JobCallbacks bằng Moto."""
    with mock_aws():
        region = "ap-southeast-1"
        dynamodb = boto3.resource("dynamodb", region_name=region)

        doc_table = dynamodb.create_table(
            TableName="test-documents",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"}
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "document_type", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"}
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI-status",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"}
                    ],
                    "Projection": {"ProjectionType": "ALL"}
                },
                {
                    "IndexName": "GSI-type",
                    "KeySchema": [
                        {"AttributeName": "document_type", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"}
                    ],
                    "Projection": {"ProjectionType": "ALL"}
                }
            ]
        )

        cb_table = dynamodb.create_table(
            TableName="test-job-callbacks",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}]
        )

        yield doc_table, cb_table


def test_dynamodb_transition_queued_to_processing(dynamodb_tables):
    """Kiểm tra Step Functions cập nhật QUEUED -> PROCESSING có điều kiện."""
    doc_table, _ = dynamodb_tables
    user_id = "test-user-1"
    doc_id = "doc-001"
    pk = f"USER#{user_id}"
    sk = f"DOC#{doc_id}"

    doc_table.put_item(
        Item={
            "PK": pk,
            "SK": sk,
            "document_id": doc_id,
            "user_id": user_id,
            "document_type": "INVOICE",
            "status": "QUEUED",
            "created_at": "2024-01-10T10:00:00Z"
        }
    )

    now = "2024-01-10T10:00:05Z"
    exec_id = "arn:aws:states:ap-southeast-1:123456789012:execution:pipeline:exec-01"
    doc_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #status = :processing, updated_at = :now, sfn_execution_id = :exec_id",
        ConditionExpression="attribute_exists(PK) AND (#status = :queued OR (#status = :processing AND sfn_execution_id = :exec_id))",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":queued": "QUEUED",
            ":processing": "PROCESSING",
            ":now": now,
            ":exec_id": exec_id
        }
    )

    item = doc_table.get_item(Key={"PK": pk, "SK": sk})["Item"]
    assert item["status"] == "PROCESSING"
    assert item["sfn_execution_id"] == exec_id


def test_fencing_token_prevents_zombie_execution_overwrite(dynamodb_tables):
    """
    KIỂM THỬ KHÓA QUYỀN SỞ HỮU (FENCING TOKEN / OWNERSHIP LOCKING):
    Execution B chạy sau cố tình giành quyền sở hữu khi tài liệu đang PROCESSING bởi Execution A
    sẽ bị ConditionalCheckFailedException ném ra ngay từ SetProcessingStatus.
    """
    doc_table, _ = dynamodb_tables
    pk = "USER#user-999"
    sk = "DOC#doc-race-condition"
    exec_a = "arn:aws:states:ap-southeast-1:123456789012:execution:pipeline:exec-A"
    exec_b = "arn:aws:states:ap-southeast-1:123456789012:execution:pipeline:exec-B"

    # 1. Execution A bắt đầu và nắm quyền sở hữu
    doc_table.put_item(
        Item={
            "PK": pk,
            "SK": sk,
            "status": "PROCESSING",
            "sfn_execution_id": exec_a,
            "created_at": "2024-01-10T10:00:00Z"
        }
    )

    # 2. Execution B chạy sau, cố gắng chiếm quyền sở hữu qua SetProcessingStatus -> Bị từ chối!
    with pytest.raises(ClientError) as exc_takeover:
        doc_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET #status = :processing, updated_at = :now, sfn_execution_id = :exec_b",
            ConditionExpression="attribute_exists(PK) AND (#status = :queued OR (#status = :processing AND sfn_execution_id = :exec_b))",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":queued": "QUEUED",
                ":processing": "PROCESSING",
                ":exec_b": exec_b,
                ":now": "2024-01-10T10:01:00Z"
            }
        )
    assert exc_takeover.value.response["Error"]["Code"] == "ConditionalCheckFailedException"

    # 3. Cùng execution A retry SetProcessingStatus -> Thành công vì đúng exec_a!
    doc_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #status = :processing, updated_at = :now, sfn_execution_id = :exec_a",
        ConditionExpression="attribute_exists(PK) AND (#status = :queued OR (#status = :processing AND sfn_execution_id = :exec_a))",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":queued": "QUEUED",
            ":processing": "PROCESSING",
            ":exec_a": exec_a,
            ":now": "2024-01-10T10:02:00Z"
        }
    )

    current_item = doc_table.get_item(Key={"PK": pk, "SK": sk})["Item"]
    assert current_item["sfn_execution_id"] == exec_a


def test_replaying_succeeded_document_does_not_overwrite_with_failed(dynamodb_tables):
    """Bảo vệ trạng thái SUCCEEDED không bao giờ bị ghi đè thành FAILED."""
    doc_table, _ = dynamodb_tables
    pk = "USER#test-user-1"
    sk = "DOC#doc-completed"

    doc_table.put_item(
        Item={
            "PK": pk,
            "SK": sk,
            "document_id": "doc-completed",
            "user_id": "test-user-1",
            "status": "SUCCEEDED",
            "confidence": 98,
            "extracted": json.dumps({"vendor": "Vinamilk", "total_amount": "15,400,000"})
        }
    )

    with pytest.raises(ClientError) as exc:
        doc_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET #status = :processing",
            ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :processing)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":queued": "QUEUED", ":processing": "PROCESSING"}
        )
    assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"

    with pytest.raises(ClientError) as exc_fail:
        doc_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET #status = :failed, error_reason = :err",
            ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :processing)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":failed": "FAILED",
                ":queued": "QUEUED",
                ":processing": "PROCESSING",
                ":err": "Some error"
            }
        )
    assert exc_fail.value.response["Error"]["Code"] == "ConditionalCheckFailedException"

    item = doc_table.get_item(Key={"PK": pk, "SK": sk})["Item"]
    assert item["status"] == "SUCCEEDED"


def test_dynamodb_transition_processing_to_succeeded(dynamodb_tables):
    """Kiểm tra ghi nhận kết quả thành công và truy vấn qua GSI-status, GSI-type."""
    doc_table, _ = dynamodb_tables
    pk = "USER#test-user-1"
    sk = "DOC#doc-002"

    doc_table.put_item(
        Item={
            "PK": pk,
            "SK": sk,
            "document_id": "doc-002",
            "user_id": "test-user-1",
            "document_type": "INVOICE",
            "status": "PROCESSING",
            "created_at": "2024-01-10T10:00:00Z"
        }
    )

    extracted_data = json.dumps({"vendor": "Vinamilk", "total_amount": "15,400,000"})
    doc_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #status = :succeeded, s3_result_key = :res_key, extracted = :extracted, confidence = :conf",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":succeeded": "SUCCEEDED",
            ":res_key": "processed/test-user-1/2024/01/doc-002.json",
            ":extracted": extracted_data,
            ":conf": 98
        }
    )

    item = doc_table.get_item(Key={"PK": pk, "SK": sk})["Item"]
    assert item["status"] == "SUCCEEDED"
    assert "Vinamilk" in item["extracted"]

    resp = doc_table.query(
        IndexName="GSI-status",
        KeyConditionExpression="#status = :s",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":s": "SUCCEEDED"}
    )
    assert len(resp["Items"]) == 1
    assert resp["Items"][0]["document_id"] == "doc-002"

    resp_type = doc_table.query(
        IndexName="GSI-type",
        KeyConditionExpression="document_type = :dt",
        ExpressionAttributeValues={":dt": "INVOICE"}
    )
    assert len(resp_type["Items"]) == 1


def test_dynamodb_transition_processing_to_needs_review(dynamodb_tables):
    """Kiểm tra ghi nhận trạng thái NEEDS_REVIEW kèm cảnh báo warnings."""
    doc_table, _ = dynamodb_tables
    pk = "USER#test-user-1"
    sk = "DOC#doc-003"

    doc_table.put_item(
        Item={
            "PK": pk,
            "SK": sk,
            "document_id": "doc-003",
            "user_id": "test-user-1",
            "document_type": "TRANSCRIPT",
            "status": "PROCESSING",
            "created_at": "2024-01-10T10:00:00Z"
        }
    )

    warnings = json.dumps(["LOW_CONFIDENCE", "BLURRY_IMAGE"])
    doc_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #status = :needs_review, warnings = :warn, confidence = :conf",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":needs_review": "NEEDS_REVIEW",
            ":warn": warnings,
            ":conf": 60
        }
    )

    item = doc_table.get_item(Key={"PK": pk, "SK": sk})["Item"]
    assert item["status"] == "NEEDS_REVIEW"
    assert "BLURRY_IMAGE" in item["warnings"]


def test_job_callbacks_table_and_ttl(dynamodb_tables):
    """Kiểm tra lưu ánh xạ job_id với task_token và TTL tự động dọn rác."""
    _, cb_table = dynamodb_tables
    job_id = "job-12345"
    token = "task-token-xyz-secret"

    save_job_callback(
        table_name="test-job-callbacks",
        job_id=job_id,
        task_token=token,
        document_id="doc-001",
        user_id="user-001",
        ttl_days=7
    )

    item = cb_table.get_item(Key={"job_id": job_id})["Item"]
    assert item["task_token"] == token
    assert item["document_id"] == "doc-001"
    now = int(time.time())
    assert item["ttl"] >= now + (6 * 86400)


# ==============================================================================
# 3. KIỂM THỬ LAMBDA MOCK WORKER & ĐẦU VÀO CỦA TV2
# ==============================================================================

def test_mock_worker_payload_generation():
    """Kiểm tra các kịch bản kết quả do Mock Worker tạo ra."""
    res_success = build_mock_ocr_result("doc-1", "user-1", "INVOICE", scenario="SUCCEEDED")
    assert res_success["status"] == "SUCCEEDED"
    assert res_success["confidence"] > 90
    assert "vendor" in res_success["extracted"]

    res_review = build_mock_ocr_result("doc-2", "user-1", "INVOICE", scenario="NEEDS_REVIEW")
    assert res_review["status"] == "NEEDS_REVIEW"
    assert len(res_review["warnings"]) > 0

    res_failed = build_mock_ocr_result("doc-3", "user-1", "INVOICE", scenario="FAILED")
    assert res_failed["status"] == "FAILED"


def test_integration_with_tv2_input_fixture(dynamodb_tables):
    """Mô phỏng toàn bộ luồng xử lý từ input fixture của TV2."""
    doc_table, cb_table = dynamodb_tables

    with open(FIXTURE_SFN_INPUT, "r", encoding="utf-8") as f:
        tv2_input = json.load(f)

    user_id = tv2_input["user_id"]
    doc_id = tv2_input["document_id"]
    doc_type = tv2_input["document_type"]

    doc_table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"DOC#{doc_id}",
            "document_id": doc_id,
            "user_id": user_id,
            "document_type": doc_type,
            "status": "QUEUED",
            "file_name": tv2_input["file_name"],
            "created_at": "2024-01-15T08:30:00Z"
        }
    )

    exec_id = "arn:aws:states:ap-southeast-1:123456789012:execution:pipeline:exec-123"
    doc_table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"},
        UpdateExpression="SET #status = :proc, updated_at = :now, sfn_execution_id = :exec_id",
        ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :proc)",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":queued": "QUEUED",
            ":proc": "PROCESSING",
            ":now": "2024-01-15T08:30:02Z",
            ":exec_id": exec_id
        }
    )

    save_job_callback(
        table_name="test-job-callbacks",
        job_id=f"job-{doc_id[:8]}",
        task_token="mock-token-abc-123",
        document_id=doc_id,
        user_id=user_id
    )

    ocr_result = build_mock_ocr_result(doc_id, user_id, doc_type, scenario="SUCCEEDED")
    doc_table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"},
        UpdateExpression="SET #status = :succ, s3_result_key = :rk, extracted = :ext, confidence = :conf",
        ConditionExpression="attribute_exists(PK) AND #status = :proc AND sfn_execution_id = :exec_id",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":succ": "SUCCEEDED",
            ":proc": "PROCESSING",
            ":exec_id": exec_id,
            ":rk": ocr_result["s3_result_key"],
            ":ext": json.dumps(ocr_result["extracted"]),
            ":conf": Decimal(str(ocr_result["confidence"]))
        }
    )

    final_item = doc_table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"})["Item"]
    assert final_item["status"] == "SUCCEEDED"
    assert final_item["s3_result_key"] == f"processed/{user_id}/2024/01/{doc_id}.json"
    assert "Vinamilk" in final_item["extracted"]


# ==============================================================================
# 4. KIỂM THỬ LAMBDA NOTIFICATION & AMAZON SES (ĐÃ TINH CHỈNH THEO REVIEW)
# ==============================================================================

def test_render_email_content_succeeded():
    """Kiểm tra render template cho kịch bản SUCCEEDED có đầy đủ hàng nghiệp vụ (Task 4.1)."""
    event = {
        "document_id": "doc-test-123",
        "file_name": "hoa_don_vat.pdf",
        "document_type": "INVOICE",
        "ocr_result": {
            "status": "SUCCEEDED",
            "confidence": 98.5,
            "extracted": {"vendor": "Vinamilk", "total_amount": "15,400,000 VND"}
        }
    }
    rendered = render_email_content(event)

    assert "[IDP] Xử lý thành công" in rendered["subject"]
    assert "hoa_don_vat.pdf" in rendered["subject"]
    assert "#28a745" in rendered["html"]
    assert "doc-test-123" in rendered["html"]
    assert "Đơn vị phát hành:" in rendered["html"]
    assert "Vinamilk" in rendered["html"]
    assert "15,400,000 VND" in rendered["html"]
    assert "Hóa đơn (INVOICE)" in rendered["html"]
    # Kiểm tra bản Plain Text cũng có thông tin chi tiết
    assert "Đơn vị phát hành: Vinamilk" in rendered["text"]
    assert "Tổng tiền thanh toán: 15,400,000 VND" in rendered["text"]


def test_render_email_content_with_json_string_extracted():
    """Kiểm tra trường hợp TV3 trả extracted dạng chuỗi JSON: Lambda tự parse json.loads thành công."""
    event = {
        "document_id": "doc-str-json",
        "file_name": "receipt.pdf",
        "document_type": "INVOICE",
        "ocr_result": {
            "status": "SUCCEEDED",
            "confidence": 95.0,
            "extracted": json.dumps({"vendor": "The Gioi Di Dong", "total_amount": "32,990,000"})
        }
    }
    rendered = render_email_content(event)
    assert "The Gioi Di Dong" in rendered["html"]
    assert "32,990,000" in rendered["html"]
    assert "The Gioi Di Dong" in rendered["text"]



def test_render_email_content_succeeded_without_warnings():
    """Kiểm tra kịch bản SUCCEEDED không hề có trường warnings (Lỗi số 1): render mượt mà không văng lỗi."""
    event = {
        "document_id": "doc-no-warn",
        "file_name": "clean_bill.pdf",
        "document_type": "INVOICE",
        "ocr_result": {
            "status": "SUCCEEDED",
            "confidence": 99.0,
            "extracted": {"vendor": "Shopee", "total_amount": "250,000"}
        }
    }
    rendered = render_email_content(event)
    assert "[IDP] Xử lý thành công" in rendered["subject"]
    assert "Cảnh báo:" not in rendered["html"]
    assert "Shopee" in rendered["html"]


def test_render_email_content_needs_review():
    """Kiểm tra render template cho kịch bản NEEDS_REVIEW có warnings và thông tin Bảng điểm."""
    event = {
        "document_id": "doc-test-456",
        "file_name": "bang_diem.pdf",
        "document_type": "TRANSCRIPT",
        "ocr_result": {
            "status": "NEEDS_REVIEW",
            "confidence": 65.0,
            "extracted": {"student_name": "Nguyen Van A", "average_score": "3.85"},
            "warnings": ["BLURRY_PAGE", "LOW_CONTRAST"]
        }
    }
    rendered = render_email_content(event)

    assert "[IDP] Cảnh báo chất lượng" in rendered["subject"]
    assert "#fd7e14" in rendered["html"]
    assert "BLURRY_PAGE" in rendered["html"]
    assert "Bảng điểm (TRANSCRIPT)" in rendered["html"]
    assert "Nguyen Van A" in rendered["html"]
    assert "3.85" in rendered["html"]
    assert "Cảnh báo: BLURRY_PAGE, LOW_CONTRAST" in rendered["text"]


def test_render_email_content_failed_with_friendly_message():
    """Kiểm tra nhánh lỗi không lộ nội dung kỹ thuật (Lỗi số 4) và document_type thiếu ra 'Không xác định' (Lỗi số 3)."""
    event = {
        "document_id": "doc-test-789",
        "file_name": "file_hong.png",
        # Không truyền document_type
        "status": "FAILED",
        "error_info": {
            "error_type": "States.Timeout",
            "Cause": "Task arn:aws:lambda:ap-southeast-1:12345:function:textract timed out after 900 seconds"
        }
    }
    rendered = render_email_content(event)

    assert "[IDP] Xử lý thất bại" in rendered["subject"]
    assert "#dc3545" in rendered["html"]
    # Kiểm tra loại tài liệu hiển thị là "Không xác định" (không bị ép thành Bảng điểm!)
    assert "Không xác định" in rendered["html"]
    assert "Không xác định" in rendered["text"]
    # Kiểm tra thông điệp thân thiện xuất hiện
    assert "Quá trình xử lý tài liệu vượt quá thời gian tối đa cho phép" in rendered["html"]
    # Đảm bảo ARN thô và Cause kỹ thuật không lộ ra email người dùng
    assert "arn:aws:lambda" not in rendered["html"]
    assert "arn:aws:lambda" not in rendered["text"]


def test_render_email_content_html_escaping_and_header_sanitize():
    """Kiểm tra chống XSS và Header Injection trên cả Subject, HTML và Plain Text."""
    malicious_event = {
        "document_id": "<script>alert('id')</script>",
        "file_name": "<img src=x onerror=alert('img')>\r\nBcc: evil@hacker.com.pdf",
        "document_type": "INVOICE",
        "status": "SUCCEEDED"
    }
    rendered = render_email_content(malicious_event)

    # 1. Subject không được chứa ký tự xuống dòng / carriage return
    assert "\r" not in rendered["subject"]
    assert "\n" not in rendered["subject"]

    # 2. HTML và Subject không được chứa raw script hoặc img tag
    assert "<script>" not in rendered["subject"]
    assert "<img" not in rendered["subject"]
    assert "<script>" not in rendered["html"]
    assert "<img" not in rendered["html"]
    # document_id được escape an toàn trong HTML
    assert "&lt;script&gt;alert" in rendered["html"]

    # 3. Plain text giữ nguyên dữ liệu sạch không bị mã hóa &lt;
    assert "&lt;" not in rendered["text"]
    assert "<script>alert('id')</script>" in rendered["text"]


def test_get_recipient_email_priority(dynamodb_tables, monkeypatch):
    """Kiểm tra toàn bộ 4 nhánh ưu tiên của get_recipient_email."""
    doc_table, _ = dynamodb_tables
    user_id = "user-priority"
    doc_id = "doc-priority"

    # Lưu email vào DynamoDB để test nhánh 3
    doc_table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"DOC#{doc_id}",
            "user_email": "db-user@domain.vn"
        }
    )
    monkeypatch.setenv("DOCUMENTS_TABLE", "test-documents")

    # Nhánh 1: DEMO_NOTIFICATION_EMAIL ưu tiên cao nhất
    monkeypatch.setenv("DEMO_NOTIFICATION_EMAIL", "sandbox@univ.edu.vn")
    assert get_recipient_email(user_id, doc_id, event_email="event@domain.vn") == "sandbox@univ.edu.vn"

    # Nhánh 2: event_email khi không có demo
    monkeypatch.delenv("DEMO_NOTIFICATION_EMAIL")
    assert get_recipient_email(user_id, doc_id, event_email="event@domain.vn") == "event@domain.vn"

    # Nhánh 3: Tra cứu DynamoDB khi không có event_email
    assert get_recipient_email(user_id, doc_id, event_email=None) == "db-user@domain.vn"

    # Nhánh 4: Khi không tìm thấy email nào -> Phải trả về None (không gửi nhầm cho Sender!)
    assert get_recipient_email("user-unknown", "doc-unknown", event_email=None) is None


def test_notification_lambda_send_email_success(monkeypatch):
    """Kiểm tra Lambda gửi SES email thành công qua Moto."""
    with mock_aws():
        region = "ap-southeast-1"
        ses = boto3.client("ses", region_name=region)
        ses.verify_email_identity(EmailAddress="noreply@idp-pipeline.aws")
        ses.verify_email_identity(EmailAddress="student@univ.edu.vn")

        monkeypatch.setenv("AWS_REGION", region)
        monkeypatch.setenv("SENDER_EMAIL", "noreply@idp-pipeline.aws")
        monkeypatch.setenv("DEMO_NOTIFICATION_EMAIL", "student@univ.edu.vn")

        event = {
            "document_id": "doc-ses-001",
            "file_name": "invoice_12.pdf",
            "document_type": "INVOICE",
            "ocr_result": {
                "status": "SUCCEEDED",
                "confidence": 99.2,
                "extracted": {"vendor": "FPT", "total_amount": "5,000,000"}
            }
        }

        resp = notification_handler(event)
        assert resp["status"] == "SENT"
        assert "message_id" in resp
        assert resp["recipient"] == "student@univ.edu.vn"


def test_notification_lambda_skipped_when_no_recipient():
    """Kiểm tra Lambda bỏ qua an toàn với SKIPPED_NO_RECIPIENT khi không tìm thấy người nhận."""
    event = {
        "document_id": "doc-no-email",
        "user_id": "user-anonymous",
        "status": "SUCCEEDED"
    }
    # Không cấu hình bất kỳ email nào
    resp = notification_handler(event)
    assert resp["status"] == "SKIPPED_NO_RECIPIENT"
    assert "Không tìm thấy" in resp["message"]


def test_notification_lambda_handles_ses_error_gracefully(monkeypatch):
    """Kiểm tra khi SES ném ClientError, Lambda nuốt lỗi và trả về FAILED_TO_SEND."""
    with mock_aws():
        region = "ap-southeast-1"
        monkeypatch.setenv("AWS_REGION", region)
        monkeypatch.setenv("SENDER_EMAIL", "unverified@idp.aws")
        monkeypatch.setenv("DEMO_NOTIFICATION_EMAIL", "unverified@univ.edu.vn")

        resp = notification_handler({"document_id": "doc-err", "status": "FAILED"})
        assert resp["status"] == "FAILED_TO_SEND"
        assert "MessageRejected" in resp["error_code"]


def test_notification_lambda_catches_all_exceptions_gracefully(monkeypatch):
    """Kiểm tra khi có Exception bất ngờ bên trong handler (Lỗi số 2), handler trả ERROR và không crash."""
    def crash_render(ev):
        raise RuntimeError("Bất ngờ gặp sự cố bộ nhớ!")

    monkeypatch.setattr("lambdas.notification.handler.render_email_content", crash_render)
    monkeypatch.setenv("DEMO_NOTIFICATION_EMAIL", "demo@test.com")

    resp = notification_handler({"document_id": "doc-crash"})
    assert resp["status"] == "ERROR"
    assert "Bất ngờ gặp sự cố" in resp["error"]
