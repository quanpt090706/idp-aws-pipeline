"""Smoke-check regression tests with synthetic files and fake AWS responses only."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from botocore.exceptions import ClientError
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import tv2_smoke as smoke


@pytest.fixture
def environment(tmp_path, monkeypatch):
    samples = tmp_path / "samples"
    samples.mkdir()
    for suffix, data in {
        "pdf": b"%PDF-1.7\nsynthetic test fixture",
        "jpg": b"\xff\xd8\xffsynthetic test fixture",
        "png": b"\x89PNG\r\n\x1a\nsynthetic test fixture",
    }.items():
        (samples / f"demo.{suffix}").write_bytes(data)
    cfg = {
        "upload_bucket": "synthetic-smoke-bucket", "documents_table": "SyntheticDocuments",
        "state_machine_arn": "arn:aws:states:us-east-1:123456789012:stateMachine:synthetic-smoke",
    }
    session = MagicMock()
    table, s3, sfn = MagicMock(), MagicMock(), MagicMock()
    session.resource.return_value.Table.return_value = table
    session.client.side_effect = {"s3": s3, "stepfunctions": sfn}.__getitem__
    state = SimpleNamespace(
        config=cfg, session=session, samples=samples, root=tmp_path, table=table, s3=s3, sfn=sfn,
        mutate=lambda payload: payload, execution_status="SUCCEEDED",
        rejected_execution=False,
    )
    documents, executions = {}, {}
    reasons = {
        "unsupported.exe": "UNSUPPORTED_EXTENSION", "empty.pdf": "FILE_EMPTY",
        "mismatch.pdf": "CONTENT_MISMATCH", "oversize.pdf": "FILE_TOO_LARGE",
    }

    def put_item(Item, **kwargs):
        documents[Item["SK"]] = dict(Item)

    def put_object(Bucket, Key, Body):
        doc = next(item for item in documents.values() if item["s3_key"] == Key)
        reason = reasons.get(doc["file_name"])
        doc["status"] = "REJECTED" if reason else "QUEUED"
        if reason:
            doc["reject_reason"] = reason
        # Deliberately opaque, multipart-style fixture: do not assume an MD5 digest.
        etag = f"opaque-server-etag-{len(documents)}-2"
        payload = {
            "schema_version": "1.0", "document_id": doc["document_id"], "user_id": doc["user_id"],
            "document_type": doc["document_type"], "bucket": Bucket, "key": Key,
            "file_name": doc["file_name"], "size_bytes": len(Body), "etag": etag, "attempt": 1,
            "content_type": {"demo.pdf": "application/pdf", "demo.jpg": "image/jpeg",
                             "demo.png": "image/png"}.get(doc["file_name"], "application/octet-stream"),
        }
        arn = smoke.execution_arn(cfg["state_machine_arn"], smoke.execution_name(payload))
        executions[arn] = (payload, reason)
        return {"ETag": f'"{etag}"'}

    def describe_execution(executionArn):
        payload, reason = executions[executionArn]
        if reason and not state.rejected_execution:
            raise ClientError({"Error": {"Code": "ExecutionDoesNotExist"}}, "DescribeExecution")
        return {"status": state.execution_status, "input": json.dumps(state.mutate(dict(payload)))}

    table.put_item.side_effect = put_item
    table.get_item.side_effect = lambda Key, **kwargs: {"Item": documents[Key["SK"]]}
    s3.put_object.side_effect = put_object
    sfn.describe_execution.side_effect = describe_execution
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    state.preflight = MagicMock(return_value=[{"check": "synthetic", "passed": True}])
    monkeypatch.setattr(smoke, "check_environment", state.preflight)
    clock = iter((0, 0, 2))  # One polling pass; no wall-clock sleeps or live AWS calls.
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    return state


def run_and_report(env):
    passed = smoke.run(env.config, env.session, env.samples, timeout=1)
    report = json.loads(next((env.root / "build" / "tv2").glob("smoke-*.json")).read_text(encoding="utf-8"))
    return passed, report


def test_matching_input_uses_server_etag_and_accepts_all_seven_cases(environment):
    passed, report = run_and_report(environment)
    assert passed
    assert len(report["cases"]) == 7
    assert all(case["passed"] for case in report["cases"])
    assert environment.s3.put_object.call_count == 7


@pytest.mark.parametrize("field,bad_value", [
    ("schema_version", "2.0"), ("document_id", "wrong-document"), ("user_id", "wrong-user"),
    ("document_type", "TRANSCRIPT-WRONG"), ("bucket", "wrong-bucket"), ("key", "wrong/key"),
    ("file_name", "wrong.pdf"), ("content_type", "application/octet-stream"),
    ("size_bytes", 999999), ("etag", "wrong-etag"), ("attempt", 2),
])
def test_any_wrong_workflow_field_fails(environment, field, bad_value):
    environment.mutate = lambda payload: {**payload, field: bad_value}
    passed, report = run_and_report(environment)
    assert passed is False
    valid_cases = [case for case in report["cases"] if not case["expected_reject_reason"]]
    assert all(field in case["input_mismatch_fields"] for case in valid_cases)
    if isinstance(bad_value, str):
        assert bad_value not in json.dumps(report)


@pytest.mark.parametrize("field", [
    "schema_version", "document_id", "user_id", "document_type", "bucket", "key",
    "file_name", "content_type", "size_bytes", "etag", "attempt",
])
def test_missing_workflow_field_fails(environment, field):
    environment.mutate = lambda payload: {key: value for key, value in payload.items() if key != field}
    assert run_and_report(environment)[0] is False


@pytest.mark.parametrize("extra", ["request_id", "queued_at", "unexpected"])
def test_extra_or_volatile_workflow_field_fails(environment, extra):
    environment.mutate = lambda payload: {**payload, extra: "synthetic-extra"}
    assert run_and_report(environment)[0] is False


def test_unknown_field_names_are_not_copied_into_evidence(environment):
    environment.mutate = lambda payload: {**payload, "private-customer-name": "private-customer-value"}
    passed, report = run_and_report(environment)
    assert passed is False
    assert "private-customer" not in json.dumps(report)
    assert all(case["input_mismatch_fields"] == ["$extra"] for case in report["cases"]
               if not case["expected_reject_reason"])


@pytest.mark.parametrize("field,cast", [("attempt", bool), ("attempt", float), ("size_bytes", float)])
def test_equal_value_with_wrong_json_type_fails(environment, field, cast):
    environment.mutate = lambda payload: {**payload, field: cast(payload[field])}
    assert run_and_report(environment)[0] is False


@pytest.mark.parametrize("payload", [None, [], "synthetic-string", 123])
def test_non_object_workflow_input_fails(environment, payload):
    environment.mutate = lambda _: payload
    assert run_and_report(environment)[0] is False


def test_malformed_workflow_json_fails_with_sanitized_evidence(environment):
    original = environment.sfn.describe_execution.side_effect

    def malformed_input(**kwargs):
        response = original(**kwargs)
        return {**response, "input": "{private-malformed-json"}

    environment.sfn.describe_execution.side_effect = malformed_input
    passed, report = run_and_report(environment)
    assert passed is False
    assert "private-malformed-json" not in json.dumps(report)
    assert all(case["input_mismatch_fields"] == ["$"] for case in report["cases"]
               if not case["expected_reject_reason"])


def test_rejected_file_must_not_have_an_execution(environment):
    environment.rejected_execution = True
    passed, report = run_and_report(environment)
    assert passed is False
    assert all(case["unexpected_execution"] for case in report["cases"] if case["expected_reject_reason"])


def test_downstream_failure_does_not_claim_ocr_success(environment):
    environment.execution_status = "FAILED"
    passed, report = run_and_report(environment)
    assert passed  # TV2 ingestion accepted; TV3/TV4 processing is a separate result.
    assert report["scope"] == "tv2_ingestion"
    assert report["ocr_verified"] is False
    assert all(case["execution_status"] == "FAILED" for case in report["cases"] if not case["expected_reject_reason"])


def test_bad_preflight_stops_before_any_write(environment):
    environment.preflight.return_value = [{"check": "synthetic", "passed": False}]
    with pytest.raises(ValueError, match="preflight"):
        smoke.run(environment.config, environment.session, environment.samples, timeout=1)
    environment.table.put_item.assert_not_called()
    environment.s3.put_object.assert_not_called()


def test_missing_samples_stop_before_aws_access(environment):
    with pytest.raises(ValueError, match="Provide anonymized"):
        smoke.run(environment.config, environment.session, environment.root / "missing", timeout=1)
    environment.preflight.assert_not_called()
    environment.session.client.assert_not_called()
    environment.session.resource.assert_not_called()
