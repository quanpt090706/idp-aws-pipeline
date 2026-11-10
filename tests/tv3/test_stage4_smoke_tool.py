import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "tv3_stage4_smoke.py"


def _module():
    spec = importlib.util.spec_from_file_location("tv3_stage4_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_execution_name_is_stable_and_attempt_sensitive():
    module = _module()
    first = module.execution_name("user-1", "doc-1", 1)
    assert first == module.execution_name("user-1", "doc-1", 1)
    assert first != module.execution_name("user-1", "doc-1", 2)
    assert first.startswith("doc-")
    assert len(first) == 36


def test_content_type_checks_supported_non_empty_file(tmp_path):
    module = _module()
    sample = tmp_path / "invoice.PDF"
    sample.write_bytes(b"%PDF-1.4\n")
    assert module.content_type_for(sample) == "application/pdf"

    unsupported = tmp_path / "invoice.txt"
    unsupported.write_text("invoice", encoding="utf-8")
    with pytest.raises(ValueError, match="PDF"):
        module.content_type_for(unsupported)


def test_execution_input_matches_workflow_contract():
    module = _module()
    payload = module.build_execution_input(
        document_id="doc-1",
        user_id="user-1",
        document_type="INVOICE",
        bucket="upload-bucket",
        key="uploads/user-1/doc-1/invoice.pdf",
        file_name="invoice.pdf",
        content_type="application/pdf",
        size_bytes=123,
        etag="etag-1",
    )
    assert payload == {
        "schema_version": "1.0",
        "document_id": "doc-1",
        "user_id": "user-1",
        "document_type": "INVOICE",
        "bucket": "upload-bucket",
        "key": "uploads/user-1/doc-1/invoice.pdf",
        "file_name": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 123,
        "etag": "etag-1",
        "attempt": 1,
    }
