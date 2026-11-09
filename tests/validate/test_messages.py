import json

import pytest

import messages

BASE = dict(
    document_id="d1",
    user_id="u1",
    document_type="INVOICE",
    bucket="b",
    key="uploads/u1/d1/a.pdf",
    file_name="a.pdf",
    content_type="application/pdf",
    size_bytes=10,
    etag="e",
    request_id="r1",
)


def test_message_has_contract_fields():
    msg = messages.build_message(**BASE, queued_at="2026-11-07T00:00:00Z")
    assert set(msg) == {
        "schema_version", "document_id", "user_id", "document_type", "bucket", "key", "file_name",
        "content_type", "size_bytes", "etag", "attempt", "request_id", "queued_at",
    }
    assert msg["schema_version"] == "1.0" and msg["attempt"] == 1


def test_to_json_roundtrip_keeps_unicode():
    msg = messages.build_message(**{**BASE, "file_name": "hóa đơn.pdf"})
    body = messages.to_json(msg)
    assert "hóa đơn.pdf" in body  # không bị escape thành \u...
    assert json.loads(body) == msg


@pytest.mark.parametrize("character", ["\ufffe", "\uffff"])
def test_json_escapes_sqs_disallowed_characters_without_changing_data(character):
    file_name = f"hóa đơn{character}.pdf"
    msg = messages.build_message(
        **{**BASE, "file_name": file_name, "key": f"uploads/u1/d1/{file_name}"}
    )
    body = messages.to_json(msg)
    # SQS's published character ranges, which Moto does not enforce.
    assert all(
        ord(c) in (9, 10, 13) or 0x20 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF
        for c in body
    )
    assert "hóa đơn" in body
    assert json.loads(body) == msg
