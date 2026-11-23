"""Handle Textract SNS completion notifications and resume Step Functions.

This Lambda retrieves every Textract result page, stores the raw response in
S3, normalizes it with the offline parsers, and sends a small callback payload
to the Step Functions task token saved by StartJob.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from urllib.parse import quote

import boto3

try:  # Package import for local tests.
    from .parsers import parse_invoice, parse_transcript
except ImportError:  # Top-level import in the Lambda ZIP.
    from parsers import parse_invoice, parse_transcript


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

MAX_EXPENSE_RESULTS = 20
MAX_DOCUMENT_RESULTS = 1_000
MAX_CALLBACK_BYTES = 240_000
SUCCESS_STATUSES = {"SUCCEEDED", "PARTIAL_SUCCESS"}
DOCUMENT_TYPE_BY_API = {
    "StartExpenseAnalysis": "INVOICE",
    "StartDocumentAnalysis": "TRANSCRIPT",
}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process all SNS messages included in the Lambda invocation."""

    notifications = _notifications(event)
    settings = _settings()
    results = [_process_notification(item, settings) for item in notifications]
    return {"processed": len(results), "results": results}


def _process_notification(
    notification: dict[str, Any], settings: dict[str, str]
) -> dict[str, Any]:
    job_id = _required_text(notification, "JobId")
    textract_status = _required_text(notification, "Status").upper()
    callback = _load_callback(settings["job_callbacks_table"], job_id)

    if callback.get("callback_status") == "COMPLETED":
        LOGGER.info("Skipping duplicate Textract callback job_id=%s", job_id)
        return {"job_id": job_id, "status": "ALREADY_COMPLETED"}

    task_token = _required_text(callback, "task_token")
    document_id = _required_text(callback, "document_id")

    if textract_status not in SUCCESS_STATUSES:
        cause = str(notification.get("StatusMessage") or textract_status)
        _send_failure(task_token, cause)
        _mark_completed(
            settings["job_callbacks_table"], job_id, "FAILED", None
        )
        LOGGER.warning(
            "Textract job failed document_id=%s job_id=%s status=%s",
            document_id,
            job_id,
            textract_status,
        )
        return {"job_id": job_id, "status": "FAILED"}

    try:
        document_type = _document_type(callback, notification)
        raw_result = _get_all_results(job_id, document_type)
        normalized = _normalize_result(document_type, raw_result)
        if textract_status == "PARTIAL_SUCCESS":
            normalized["warnings"].append(
                {
                    "code": "TEXTRACT_PARTIAL_SUCCESS",
                    "field": "document",
                    "message": "Textract returned only part of the document result.",
                }
            )

        result_key = _result_key(
            _required_text(callback, "user_id"), document_id
        )
        _store_raw_result(settings["s3_results_bucket"], result_key, raw_result)

        result_status = _result_status(normalized)
        output = {
            "status": result_status,
            "s3_result_key": result_key,
            "confidence": normalized["confidence"],
            "extracted": normalized["extracted"],
            "warnings": normalized["warnings"],
        }
        output_json = json.dumps(
            output, ensure_ascii=False, separators=(",", ":"), default=_json_default
        )
        if len(output_json.encode("utf-8")) > MAX_CALLBACK_BYTES:
            raise RuntimeError("Normalized callback exceeds the safe payload size.")

        _client("stepfunctions").send_task_success(
            taskToken=task_token,
            output=output_json,
        )
        _mark_completed(
            settings["job_callbacks_table"], job_id, result_status, result_key
        )
        LOGGER.info(
            "Completed Textract callback document_id=%s job_id=%s status=%s",
            document_id,
            job_id,
            result_status,
        )
        return {
            "job_id": job_id,
            "document_id": document_id,
            "status": result_status,
            "s3_result_key": result_key,
        }
    except Exception as error:
        LOGGER.exception(
            "Failed to process Textract result document_id=%s job_id=%s",
            document_id,
            job_id,
        )
        _send_failure(task_token, str(error))
        _mark_completed(
            settings["job_callbacks_table"], job_id, "FAILED", None
        )
        return {"job_id": job_id, "status": "FAILED"}


def _notifications(event: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(event, dict):
        raise ValueError("SNS event must be a JSON object.")

    records = event.get("Records")
    if records is None:
        if event.get("JobId") and event.get("Status"):
            return [event]
        raise ValueError("SNS event does not contain Records.")
    if not isinstance(records, list) or not records:
        raise ValueError("SNS event Records must be a non-empty list.")

    notifications: list[dict[str, Any]] = []
    for record in records:
        message = (record.get("Sns") or {}).get("Message") if isinstance(record, dict) else None
        if not isinstance(message, str):
            raise ValueError("SNS record does not contain a string Message.")
        try:
            decoded = json.loads(message)
        except json.JSONDecodeError as error:
            raise ValueError("SNS Message is not valid JSON.") from error
        if not isinstance(decoded, dict):
            raise ValueError("SNS Message must decode to a JSON object.")
        notifications.append(decoded)
    return notifications


def _settings() -> dict[str, str]:
    names = {
        "job_callbacks_table": "JOB_CALLBACKS_TABLE",
        "s3_results_bucket": "S3_RESULTS_BUCKET",
    }
    settings: dict[str, str] = {}
    missing: list[str] = []
    for setting_name, environment_name in names.items():
        value = os.environ.get(environment_name, "").strip()
        if value:
            settings[setting_name] = value
        else:
            missing.append(environment_name)
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(sorted(missing))
        )
    return settings


def _load_callback(table_name: str, job_id: str) -> dict[str, Any]:
    response = _client("dynamodb").get_item(
        TableName=table_name,
        Key={"job_id": {"S": job_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        raise LookupError(f"No callback record found for Textract job {job_id}.")
    return {name: _dynamodb_value(value) for name, value in item.items()}


def _document_type(
    callback: dict[str, Any], notification: dict[str, Any]
) -> str:
    document_type = str(callback.get("document_type") or "").upper()
    if not document_type:
        document_type = DOCUMENT_TYPE_BY_API.get(str(notification.get("API")), "")
    if document_type not in {"INVOICE", "TRANSCRIPT"}:
        raise ValueError("Cannot determine a supported document_type for callback.")
    return document_type


def _get_all_results(job_id: str, document_type: str) -> dict[str, Any]:
    textract = _client("textract")
    get_page: Callable[..., dict[str, Any]]
    if document_type == "INVOICE":
        get_page = textract.get_expense_analysis
        max_results = MAX_EXPENSE_RESULTS
    else:
        get_page = textract.get_document_analysis
        max_results = MAX_DOCUMENT_RESULTS

    combined: dict[str, Any] = {}
    next_token: str | None = None
    while True:
        arguments: dict[str, Any] = {
            "JobId": job_id,
            "MaxResults": max_results,
        }
        if next_token:
            arguments["NextToken"] = next_token
        page = get_page(**arguments)
        _merge_result_page(combined, page)
        next_token = page.get("NextToken")
        if not next_token:
            return combined


def _merge_result_page(
    combined: dict[str, Any], page: dict[str, Any]
) -> None:
    for key, value in page.items():
        if key in {"NextToken", "ResponseMetadata"}:
            continue
        if isinstance(value, list):
            combined.setdefault(key, []).extend(value)
        elif key == "DocumentMetadata" and isinstance(value, dict):
            current_pages = int((combined.get(key) or {}).get("Pages") or 0)
            new_pages = int(value.get("Pages") or 0)
            combined[key] = {**value, "Pages": max(current_pages, new_pages)}
        elif key not in combined:
            combined[key] = value


def _normalize_result(
    document_type: str, raw_result: dict[str, Any]
) -> dict[str, Any]:
    if document_type == "INVOICE":
        return parse_invoice(raw_result)
    return parse_transcript(raw_result)


def _result_status(normalized: dict[str, Any]) -> str:
    threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "80.0"))
    confidence = float(normalized.get("confidence") or 0.0)
    warnings = normalized.get("warnings") or []
    return "NEEDS_REVIEW" if warnings or confidence < threshold else "SUCCEEDED"


def _result_key(user_id: str, document_id: str) -> str:
    now = datetime.now(timezone.utc)
    safe_user_id = quote(user_id, safe="")
    safe_document_id = quote(document_id, safe="")
    return (
        f"user_id={safe_user_id}/year={now.year:04d}/month={now.month:02d}/"
        f"{safe_document_id}.json"
    )


def _store_raw_result(
    bucket: str, result_key: str, raw_result: dict[str, Any]
) -> None:
    body = json.dumps(
        raw_result, ensure_ascii=False, default=_json_default
    ).encode("utf-8")
    _client("s3").put_object(
        Bucket=bucket,
        Key=result_key,
        Body=body,
        ContentType="application/json",
    )


def _send_failure(task_token: str, cause: str) -> None:
    _client("stepfunctions").send_task_failure(
        taskToken=task_token,
        error="TextractExecutionError",
        cause=(cause or "Textract processing failed.")[:1_000],
    )


def _mark_completed(
    table_name: str,
    job_id: str,
    status: str,
    result_key: str | None,
) -> None:
    values: dict[str, dict[str, str]] = {
        ":callback_status": {"S": "COMPLETED"},
        ":result_status": {"S": status},
        ":completed_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    expression = (
        "SET callback_status = :callback_status, "
        "result_status = :result_status, completed_at = :completed_at"
    )
    if result_key is not None:
        expression += ", result_s3_key = :result_s3_key"
        values[":result_s3_key"] = {"S": result_key}
    _client("dynamodb").update_item(
        TableName=table_name,
        Key={"job_id": {"S": job_id}},
        UpdateExpression=expression,
        ExpressionAttributeValues=values,
    )


def _required_text(source: dict[str, Any], field_name: str) -> str:
    value = source.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid required field: {field_name}")
    return value.strip()


def _dynamodb_value(value: dict[str, Any]) -> Any:
    if "S" in value:
        return value["S"]
    if "N" in value:
        candidate = Decimal(value["N"])
        return int(candidate) if candidate == candidate.to_integral_value() else float(candidate)
    if "BOOL" in value:
        return bool(value["BOOL"])
    if "NULL" in value:
        return None
    raise ValueError("Unsupported DynamoDB callback attribute type.")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _client(service_name: str) -> Any:
    return boto3.client(service_name)
