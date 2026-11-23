"""Start an asynchronous Amazon Textract job for Step Functions.

The workflow uses ``waitForTaskToken``. This Lambda starts Textract and stores
the mapping from Textract ``JobId`` to the task token. The SNS callback Lambda
later uses that mapping to resume the waiting execution.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

import boto3


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

CALLBACK_TTL_SECONDS = 7 * 24 * 60 * 60
SUPPORTED_DOCUMENT_TYPES = {"INVOICE", "TRANSCRIPT"}
REQUIRED_FIELDS = (
    "document_id",
    "user_id",
    "document_type",
    "bucket",
    "key",
    "task_token",
)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Start Textract and persist callback information for the SNS handler."""

    request = _validated_request(event)
    settings = _settings()
    textract = _client("textract")
    dynamodb = _client("dynamodb")

    start_arguments: dict[str, Any] = {
        "DocumentLocation": {
            "S3Object": {
                "Bucket": request["bucket"],
                "Name": request["key"],
            }
        },
        "ClientRequestToken": _request_token(request),
        "JobTag": _job_tag(request["document_id"]),
        "NotificationChannel": {
            "SNSTopicArn": settings["sns_topic_arn"],
            "RoleArn": settings["textract_role_arn"],
        },
    }

    if request["document_type"] == "INVOICE":
        response = textract.start_expense_analysis(**start_arguments)
    else:
        response = textract.start_document_analysis(
            **start_arguments,
            FeatureTypes=["TABLES", "FORMS"],
        )

    job_id = str(response.get("JobId") or "").strip()
    if not job_id:
        raise RuntimeError("Textract did not return JobId.")

    expires_at = int(time.time()) + CALLBACK_TTL_SECONDS
    dynamodb.put_item(
        TableName=settings["job_callbacks_table"],
        Item={
            "job_id": {"S": job_id},
            "task_token": {"S": request["task_token"]},
            "document_id": {"S": request["document_id"]},
            "user_id": {"S": request["user_id"]},
            "document_type": {"S": request["document_type"]},
            "attempt": {"N": str(request["attempt"])},
            "ttl": {"N": str(expires_at)},
        },
    )

    LOGGER.info(
        "Started Textract job document_id=%s document_type=%s job_id=%s attempt=%s",
        request["document_id"],
        request["document_type"],
        job_id,
        request["attempt"],
    )
    return {
        "job_id": job_id,
        "document_id": request["document_id"],
        "document_type": request["document_type"],
        "status": "PROCESSING",
    }


def _validated_request(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("StartJob input must be a JSON object.")

    request: dict[str, Any] = {}
    for field_name in REQUIRED_FIELDS:
        value = event.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing or invalid required field: {field_name}")
        request[field_name] = value.strip()

    request["document_type"] = request["document_type"].upper()
    if request["document_type"] not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError("document_type must be either INVOICE or TRANSCRIPT.")

    attempt = event.get("attempt", 1)
    if isinstance(attempt, bool):
        raise ValueError("attempt must be a positive integer.")
    try:
        request["attempt"] = int(attempt)
    except (TypeError, ValueError) as error:
        raise ValueError("attempt must be a positive integer.") from error
    if request["attempt"] < 1:
        raise ValueError("attempt must be a positive integer.")

    return request


def _settings() -> dict[str, str]:
    names = {
        "sns_topic_arn": "SNS_TOPIC_ARN",
        "textract_role_arn": "TEXTRACT_ROLE_ARN",
        "job_callbacks_table": "JOB_CALLBACKS_TABLE",
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


def _request_token(request: dict[str, Any]) -> str:
    """Return a stable token so retries do not start a second paid OCR job."""

    source = (
        f"{request['document_id']}:{request['document_type']}:{request['attempt']}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _job_tag(document_id: str) -> str:
    usable = "".join(
        character
        for character in document_id
        if character.isascii()
        and (character.isalnum() or character in "_.-:")
    )
    return (usable or hashlib.sha256(document_id.encode("utf-8")).hexdigest())[:64]


def _client(service_name: str) -> Any:
    return boto3.client(service_name)
