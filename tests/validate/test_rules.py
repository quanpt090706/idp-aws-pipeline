import pytest

import rules
from helpers import JPG_BYTES, PDF_BYTES, PNG_BYTES

MAX = 10 * 1024 * 1024


@pytest.mark.parametrize("name", ["a.pdf", "a.PDF", "a.jpg", "a.JPEG", "a.png", "a.b.c.pdf"])
def test_basic_accepts_allowed_extensions(name):
    assert rules.validate_basic(name, 1000, MAX).ok


@pytest.mark.parametrize("name", ["a.exe", "a.zip", "a.docx", "a", "a.", ".pdf.exe", "a.tiff"])
def test_basic_rejects_other_extensions(name):
    r = rules.validate_basic(name, 1000, MAX)
    assert not r.ok and r.reason == rules.UNSUPPORTED_EXTENSION


def test_basic_size_boundaries():
    assert rules.validate_basic("a.pdf", MAX, MAX).ok  # đúng bằng giới hạn: được
    assert rules.validate_basic("a.pdf", MAX + 1, MAX).reason == rules.FILE_TOO_LARGE
    assert rules.validate_basic("a.pdf", 0, MAX).reason == rules.FILE_EMPTY


def test_extension_checked_before_size():
    assert rules.validate_basic("a.exe", MAX * 5, MAX).reason == rules.UNSUPPORTED_EXTENSION


@pytest.mark.parametrize(
    "name,header",
    [("a.pdf", PDF_BYTES[:16]), ("a.jpg", JPG_BYTES[:16]), ("a.jpeg", JPG_BYTES[:16]), ("a.png", PNG_BYTES[:16])],
)
def test_content_matches_extension(name, header):
    assert rules.validate_content(name, header).ok


@pytest.mark.parametrize(
    "name,header",
    [
        ("a.pdf", PNG_BYTES[:16]),  # đổi đuôi png -> pdf
        ("a.png", PDF_BYTES[:16]),
        ("a.jpg", b"MZ\x90\x00" + b"\x00" * 12),  # file .exe đổi đuôi
        ("a.pdf", b""),  # rỗng
        ("a.pdf", b"<html>"),
    ],
)
def test_content_mismatch(name, header):
    r = rules.validate_content(name, header)
    assert not r.ok and r.reason == rules.CONTENT_MISMATCH


@pytest.mark.parametrize("t", ["INVOICE", "TRANSCRIPT"])
def test_document_type_ok(t):
    assert rules.validate_document_type(t).ok


@pytest.mark.parametrize("t", [None, "", "invoice", "RECEIPT"])
def test_document_type_invalid(t):
    assert rules.validate_document_type(t).reason == rules.INVALID_DOCUMENT_TYPE
