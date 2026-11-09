import pytest

from helpers import make_s3_event
from s3_event import InvalidKeyError, parse_s3_event, parse_upload_key


def test_parse_event_url_decodes_key():
    key = "uploads/u1/d1/hóa đơn tháng 1.pdf"  # có dấu tiếng Việt + khoảng trắng
    objs = parse_s3_event(make_s3_event("b", key, size=99, etag="e1"))
    assert len(objs) == 1
    assert objs[0].key == key  # đã decode đúng
    assert (objs[0].bucket, objs[0].size, objs[0].etag) == ("b", 99, "e1")


def test_plus_sign_in_key_is_a_space():
    event = make_s3_event("b", "x")
    event["Records"][0]["s3"]["object"]["key"] = "uploads/u1/d1/a+b.pdf"
    assert parse_s3_event(event)[0].key == "uploads/u1/d1/a b.pdf"


def test_non_created_events_are_ignored():
    assert parse_s3_event(make_s3_event("b", "uploads/u/d/a.pdf", event_name="ObjectRemoved:Delete")) == []


@pytest.mark.parametrize("event", [{}, None, {"Records": []}, {"Service": "Amazon S3", "Event": "s3:TestEvent"}])
def test_empty_or_test_events(event):
    assert parse_s3_event(event) == []


def test_parse_upload_key_ok():
    k = parse_upload_key("uploads/abc-123/doc_9/hoa don.PDF")
    assert (k.user_id, k.document_id, k.file_name) == ("abc-123", "doc_9", "hoa don.PDF")


@pytest.mark.parametrize(
    "key",
    [
        "other/u/d/a.pdf",  # sai prefix
        "uploads/u/a.pdf",  # thiếu document_id
        "uploads/u/d/sub/a.pdf",  # thừa cấp thư mục
        "uploads/u/d/",  # key của "thư mục"
        "uploads/u u/d/a.pdf",  # user_id có khoảng trắng
        "uploads/u/d:1/a.pdf",  # document_id có ký tự cấm
        "uploads/u/" + "d" * 65 + "/a.pdf",  # document_id quá dài
        "uploads/u\n/d/a.pdf",
        "uploads/u/d/a\n.pdf",
        "uploads/u/d/a\\b.pdf",
    ],
)
def test_parse_upload_key_rejects_bad_keys(key):
    with pytest.raises(InvalidKeyError):
        parse_upload_key(key)
