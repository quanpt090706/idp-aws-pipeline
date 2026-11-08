"""Live dev-only upload tests. Explicit --confirm-dev-write and account guard required."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

from botocore.exceptions import BotoCoreError, ClientError

from tv2_preflight import checked_session, check_environment, load_config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas" / "workflow-starter"))
from app import execution_arn, execution_name  # noqa: E402


def input_mismatches(payload, expected):
    """Compare the full input contract, including JSON types, without saving values."""
    if not isinstance(payload, dict):
        return ["$"]
    fields = [
        field for field, value in expected.items()
        if field not in payload or type(payload[field]) is not type(value) or payload[field] != value
    ]
    if payload.keys() - expected.keys():
        fields.append("$extra")  # Unexpected field names may themselves contain private data.
    return sorted(fields)


def run(config, session, sample_dir, timeout):
    samples = Path(sample_dir)
    required = [samples / f"demo.{suffix}" for suffix in ("pdf", "jpg", "png")]
    if not all(path.is_file() for path in required):
        raise ValueError("Provide anonymized demo.pdf, demo.jpg, demo.png in --samples before any AWS write")
    if not all(0 < path.stat().st_size <= 10 * 1024 * 1024 for path in required):
        raise ValueError("Each valid sample must be non-empty and at most 10 MiB")
    checks = check_environment(config, session)
    if not all(check["passed"] for check in checks):
        raise ValueError("Run preflight and fix failed environment checks before smoke testing")
    ddb = session.resource("dynamodb").Table(config["documents_table"])
    s3 = session.client("s3")
    sfn = session.client("stepfunctions")
    run_id = uuid.uuid4().hex[:12]
    user = f"tv2-test-{run_id}"
    cases = [(path.name, path.read_bytes(), None) for path in required]
    cases += [
        ("unsupported.exe", b"MZ-synthetic", "UNSUPPORTED_EXTENSION"),
        ("empty.pdf", b"", "FILE_EMPTY"),
        ("mismatch.pdf", b"\x89PNG\r\n\x1a\nsynthetic", "CONTENT_MISMATCH"),
        ("oversize.pdf", b"%PDF-" + bytes(10 * 1024 * 1024), "FILE_TOO_LARGE"),
    ]
    manifest = {
        "run_id": run_id, "user_id": user, "scope": "tv2_ingestion", "ocr_verified": False, "cases": [],
        "observation": {
            "scope": "bounded_polling_after_uploads", "requested_seconds": timeout,
            "elapsed_seconds": None, "complete": False, "permanent_absence_proven": False,
        },
    }
    expected_inputs = {}
    output = ROOT / "build" / "tv2"
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / f"smoke-{run_id}.json"
    for index, (filename, body, reject_reason) in enumerate(cases):
        doc_id = str(uuid.uuid4())
        key = f"uploads/{user}/{doc_id}/{filename}"
        document_type = "INVOICE" if index % 2 == 0 else "TRANSCRIPT"
        now = datetime.now(timezone.utc).isoformat()
        ddb.put_item(Item={
            "PK": f"USER#{user}", "SK": f"DOC#{doc_id}", "user_id": user, "document_id": doc_id,
            "file_name": filename, "document_type": document_type,
            "status": "UPLOAD_PENDING", "s3_key": key, "created_at": now, "updated_at": now,
        }, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
        # Record the generated resources before upload so interrupted tests remain recoverable.
        case = {"document_id": doc_id, "s3_key": key, "expected_reject_reason": reject_reason}
        manifest["cases"].append(case)
        report_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        uploaded = s3.put_object(Bucket=config["upload_bucket"], Key=key, Body=body)
        if reject_reason is None:
            expected_inputs[doc_id] = {
                "schema_version": "1.0", "document_id": doc_id, "user_id": user,
                "document_type": document_type, "bucket": config["upload_bucket"], "key": key,
                "file_name": filename, "content_type": {"demo.pdf": "application/pdf",
                    "demo.jpg": "image/jpeg", "demo.png": "image/png"}[filename],
                "size_bytes": len(body), "etag": uploaded["ETag"].strip('"'), "attempt": 1,
            }
    observation_started = time.monotonic()
    deadline = observation_started + timeout
    while True:
        poll_started = time.monotonic()
        for case in manifest["cases"]:
            item = ddb.get_item(Key={"PK": f"USER#{user}", "SK": f'DOC#{case["document_id"]}'}, ConsistentRead=True).get("Item", {})
            case["status"] = item.get("status")
            expected = case["expected_reject_reason"]
            arn = execution_arn(config["state_machine_arn"], execution_name({
                "user_id": user, "document_id": case["document_id"], "attempt": 1,
            }))
            if expected:
                if item.get("status") == "REJECTED" and item.get("reject_reason") != expected:
                    case["reject_reason_mismatch"] = True
                case["passed"] = (item.get("status") == "REJECTED" and item.get("reject_reason") == expected
                                  and not case.get("reject_reason_mismatch") and not case.get("unexpected_execution"))
                try:
                    sfn.describe_execution(executionArn=arn)
                    case["passed"] = False
                    case["unexpected_execution"] = True
                except ClientError as error:
                    if error.response["Error"]["Code"] != "ExecutionDoesNotExist":
                        raise
            else:
                try:
                    execution = sfn.describe_execution(executionArn=arn)
                    case["execution_status"] = execution["status"]
                    try:
                        payload = json.loads(execution["input"])
                    except json.JSONDecodeError:
                        payload = None
                    mismatches = input_mismatches(payload, expected_inputs[case["document_id"]])
                    case["input_mismatch_fields"] = sorted(set(case.get("input_mismatch_fields", [])) | set(mismatches))
                    case["passed"] = (item.get("status") in {"QUEUED", "PROCESSING", "SUCCEEDED", "NEEDS_REVIEW", "FAILED"}
                                      and not case["input_mismatch_fields"])
                except ClientError as error:
                    if error.response["Error"]["Code"] != "ExecutionDoesNotExist":
                        raise
                    case["passed"] = False
        # Finish a full scan begun at/after the deadline, even if an earlier scan was slow.
        elapsed = time.monotonic() - observation_started
        if poll_started >= deadline:
            break
        if elapsed < timeout:
            time.sleep(min(2, timeout - elapsed))
    manifest["observation"].update(elapsed_seconds=round(elapsed, 3), complete=True)
    report_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Evidence saved: {report_path.relative_to(ROOT)}")
    return all(case.get("passed") for case in manifest["cases"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--profile", default="academy-lab")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Observation window after uploads (default: 180 seconds), ending with a full scan; absence is bounded.")
    parser.add_argument("--confirm-dev-write", action="store_true")
    args = parser.parse_args()
    if not args.confirm_dev_write:
        parser.error("This creates dev S3 objects/Documents records; add --confirm-dev-write only for the intended lab")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        config = load_config(args.config)
        return 0 if run(config, checked_session(config, args.profile), args.samples, args.timeout) else 1
    except (ValueError, OSError, BotoCoreError, ClientError) as error:
        code = error.response["Error"]["Code"] if isinstance(error, ClientError) else type(error).__name__
        print(json.dumps({"status": "FAILED", "error_type": code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
