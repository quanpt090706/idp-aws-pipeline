"""
Kiểm thử bộ phận của Thành viên 4 (Data & Orchestration):
1. Tính toàn vẹn cấu trúc State Machine ASL JSON.
2. Vòng đời dữ liệu và cập nhật có điều kiện trong DynamoDB Single-Table (GSI-status, GSI-type).
3. Bảng phụ JobCallbacks và cơ chế TTL.
4. Lambda Mock Worker phản hồi cho các kịch bản SUCCEEDED, NEEDS_REVIEW, FAILED.
"""
import json
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

ROOT_DIR = Path(__file__).resolve().parents[2]
ASL_FILE = ROOT_DIR / "infra" / "step_functions" / "state_machine.asl.json"
FIXTURE_SFN_INPUT = ROOT_DIR / "tests" / "fixtures" / "step_functions_input.json"


# ==============================================================================
# 1. KIỂM THỬ CẤU TRÚC ASL JSON CỦA STATE MACHINE
# ==============================================================================

def test_asl_json_syntax_and_structure():
    """Đảm bảo file ASL JSON hợp lệ, đầy đủ các State và đúng quy tắc chuyển tiếp."""
    assert ASL_FILE.exists(), "Không tìm thấy file state_machine.asl.json"
    with open(ASL_FILE, "r", encoding="utf-8") as f:
        asl = json.load(f)

    assert asl["StartAt"] == "SetProcessingStatus"
    states = asl["States"]

    # 1. Kiểm tra State SetProcessingStatus
    set_proc = states["SetProcessingStatus"]
    assert set_proc["Type"] == "Task"
    assert set_proc["Resource"] == "arn:aws:states:::dynamodb:updateItem"
    assert "attribute_exists(PK)" in set_proc["Parameters"]["ConditionExpression"]
    assert "#status IN (:queued, :processing)" in set_proc["Parameters"]["ConditionExpression"]
    assert set_proc["Next"] == "RouteByDocumentType"
    assert len(set_proc["Retry"]) > 0
    assert len(set_proc["Catch"]) > 0

    # 2. Kiểm tra State RouteByDocumentType
    router = states["RouteByDocumentType"]
    assert router["Type"] == "Choice"
    choices = {c["StringEquals"]: c["Next"] for c in router["Choices"]}
    assert choices.get("INVOICE") == "WaitForTextractInvoiceAnalysis"
    assert choices.get("TRANSCRIPT") == "WaitForTextractTranscriptAnalysis"
    assert router["Default"] == "HandleInvalidDocumentType"

    # 3. Kiểm tra các State chờ TaskToken callback
    for st_name in ("WaitForTextractInvoiceAnalysis", "WaitForTextractTranscriptAnalysis"):
        st = states[st_name]
        assert st["Type"] == "Task"
        assert st["Resource"] == "arn:aws:states:::lambda:invoke.waitForTaskToken"
        assert st["TimeoutSeconds"] == 900
        assert st["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"
        assert st["Next"] == "EvaluateExtractionResult"
        assert any("Textract.ThrottlingException" in r["ErrorEquals"] for r in st["Retry"])
        assert any("States.ALL" in c["ErrorEquals"] for c in st["Catch"])

    # 4. Kiểm tra EvaluateExtractionResult
    eval_state = states["EvaluateExtractionResult"]
    assert eval_state["Type"] == "Choice"
    eval_choices = {c["StringEquals"]: c["Next"] for c in eval_state["Choices"]}
    assert eval_choices.get("SUCCEEDED") == "UpdateStatusSucceeded"
    assert eval_choices.get("NEEDS_REVIEW") == "UpdateStatusNeedsReview"
    assert eval_state["Default"] == "HandleFailure"

    # 5. Kiểm tra các State cập nhật trạng thái cuối
    assert states["UpdateStatusSucceeded"]["Type"] == "Task"
    assert states["UpdateStatusSucceeded"]["Resource"] == "arn:aws:states:::dynamodb:updateItem"
    assert states["UpdateStatusNeedsReview"]["Type"] == "Task"
    assert states["HandleFailure"]["Type"] == "Task"
    assert states["WorkflowSucceeded"]["Type"] == "Succeed"
    assert states["WorkflowFailed"]["Type"] == "Fail"


# ==============================================================================
# 2. KIỂM THỬ DYNAMODB SINGLE-TABLE LIFECYCLE (MOTO)
# ==============================================================================

@pytest.fixture
def dynamodb_tables():
    """Khởi tạo bảng Documents và JobCallbacks bằng Moto."""
    with mock_aws():
        region = "ap-southeast-1"
        dynamodb = boto3.resource("dynamodb", region_name=region)

        # Tạo bảng Documents với 2 GSI
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

        # Tạo bảng JobCallbacks kèm hash_key job_id
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

    # Giả lập TV2 đã ghi QUEUED vào bảng
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

    # 1. State Machine thực hiện cập nhật có điều kiện sang PROCESSING
    now = "2024-01-10T10:00:05Z"
    exec_id = "arn:aws:states:ap-southeast-1:123456789012:execution:pipeline:exec-01"
    doc_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #status = :processing, updated_at = :now, sfn_execution_id = :exec_id",
        ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :processing)",
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

    # 2. Kiểm tra tính Idempotent khi Step Functions retry:
    # Bản ghi đã ở PROCESSING thì update lại vẫn phải thành công không bị Exception!
    doc_table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET #status = :processing, updated_at = :now2",
        ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :processing)",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":queued": "QUEUED",
            ":processing": "PROCESSING",
            ":now2": "2024-01-10T10:00:06Z"
        }
    )
    assert doc_table.get_item(Key={"PK": pk, "SK": sk})["Item"]["status"] == "PROCESSING"

    # 3. Bản ghi ở trạng thái khác (ví dụ REJECTED) hoặc không tồn tại sẽ bị từ chối
    doc_table.put_item(
        Item={"PK": "USER#bad", "SK": "DOC#bad", "status": "REJECTED"}
    )
    with pytest.raises(ClientError) as exc:
        doc_table.update_item(
            Key={"PK": "USER#bad", "SK": "DOC#bad"},
            UpdateExpression="SET #status = :processing",
            ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :processing)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":queued": "QUEUED", ":processing": "PROCESSING"}
        )
    assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


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

    # State Machine cập nhật sang SUCCEEDED
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

    # Kiểm tra truy vấn bằng GSI-status
    resp = doc_table.query(
        IndexName="GSI-status",
        KeyConditionExpression="#status = :s",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":s": "SUCCEEDED"}
    )
    assert len(resp["Items"]) == 1
    assert resp["Items"][0]["document_id"] == "doc-002"

    # Kiểm tra truy vấn bằng GSI-type
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
    # TTL phải là mốc tương lai sau khoảng 7 ngày (+- vài giây)
    now = int(time.time())
    assert item["ttl"] >= now + (6 * 86400)


# ==============================================================================
# 3. KIỂM THỬ LAMBDA MOCK WORKER & ĐẦU VÀO CỦA TV2
# ==============================================================================

def test_mock_worker_payload_generation():
    """Kiểm tra các kịch bản kết quả do Mock Worker tạo ra."""
    # 1. Kịch bản SUCCEEDED
    res_success = build_mock_ocr_result("doc-1", "user-1", "INVOICE", scenario="SUCCEEDED")
    assert res_success["status"] == "SUCCEEDED"
    assert res_success["confidence"] > 90
    assert "vendor" in res_success["extracted"]

    # 2. Kịch bản NEEDS_REVIEW
    res_review = build_mock_ocr_result("doc-2", "user-1", "INVOICE", scenario="NEEDS_REVIEW")
    assert res_review["status"] == "NEEDS_REVIEW"
    assert len(res_review["warnings"]) > 0

    # 3. Kịch bản FAILED
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

    # Bước 1: TV2 đã xếp hàng QUEUED
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

    # Bước 2: State Machine bắt đầu -> đổi sang PROCESSING
    doc_table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"},
        UpdateExpression="SET #status = :proc, updated_at = :now",
        ConditionExpression="attribute_exists(PK) AND #status IN (:queued, :proc)",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":queued": "QUEUED",
            ":proc": "PROCESSING",
            ":now": "2024-01-15T08:30:02Z"
        }
    )

    # Bước 3: Mock worker nhận lệnh, lưu token vào JobCallbacks
    mock_event = {
        "document_id": doc_id,
        "user_id": user_id,
        "document_type": doc_type,
        "task_token": "mock-token-abc-123",
        "mock_scenario": "SUCCEEDED"
    }
    save_job_callback(
        table_name="test-job-callbacks",
        job_id=f"job-{doc_id[:8]}",
        task_token="mock-token-abc-123",
        document_id=doc_id,
        user_id=user_id
    )

    # Bước 4: Giả lập trả kết quả bóc tách và ghi nhận SUCCEEDED
    ocr_result = build_mock_ocr_result(doc_id, user_id, doc_type, scenario="SUCCEEDED")
    doc_table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"},
        UpdateExpression="SET #status = :succ, s3_result_key = :rk, extracted = :ext, confidence = :conf",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":succ": "SUCCEEDED",
            ":rk": ocr_result["s3_result_key"],
            ":ext": json.dumps(ocr_result["extracted"]),
            ":conf": Decimal(str(ocr_result["confidence"]))
        }
    )

    # Kiểm tra trạng thái cuối cùng
    final_item = doc_table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"})["Item"]
    assert final_item["status"] == "SUCCEEDED"
    assert final_item["s3_result_key"] == f"processed/{user_id}/2024/01/{doc_id}.json"
    assert "Vinamilk" in final_item["extracted"]
