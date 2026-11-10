"""Extract readable text locally without importing an AWS SDK.

Text PDFs use Poppler's ``pdftotext``. Image-only PDFs and image uploads use
Tesseract. Keeping this adapter separate makes it disposable when Textract is
available again.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class LocalOcrUnavailable(RuntimeError):
    """Raised when a required local executable is not installed."""


class LocalOcrError(RuntimeError):
    """Raised when the local OCR command cannot read a document."""


@dataclass(frozen=True)
class ExtractedText:
    text: str
    confidence: float
    engine: str


def extract_text(path: Path) -> ExtractedText:
    """Extract text from a PDF, PNG, or JPEG using local executables."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        embedded = _pdf_text(path)
        if len("".join(embedded.split())) >= 30:
            return ExtractedText(embedded, 99.0, "pdftotext")
        return _ocr_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg"}:
        return _tesseract(path)
    raise LocalOcrError("Chỉ hỗ trợ PDF, JPG, JPEG hoặc PNG.")


def _require(command: str, install_hint: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        raise LocalOcrUnavailable(
            f"Thiếu {command}. Trên Ubuntu chạy: sudo apt install {install_hint}"
        )
    return executable


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise LocalOcrError("OCR local vượt quá thời gian chờ 120 giây.") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()
        message = detail[-1] if detail else "không đọc được tài liệu"
        raise LocalOcrError(f"OCR local thất bại: {message[:300]}") from error


def _pdf_text(path: Path) -> str:
    executable = _require("pdftotext", "poppler-utils")
    return _run([executable, "-layout", str(path), "-"]).stdout


def _ocr_pdf(path: Path) -> ExtractedText:
    executable = _require("pdftoppm", "poppler-utils")
    _require("tesseract", "tesseract-ocr tesseract-ocr-eng")
    with tempfile.TemporaryDirectory(prefix="idp-local-ocr-") as directory:
        prefix = Path(directory) / "page"
        _run([executable, "-png", "-r", "250", str(path), str(prefix)])
        pages = sorted(Path(directory).glob("page-*.png"))
        if not pages:
            raise LocalOcrError("Không thể chuyển PDF thành ảnh để OCR.")
        results = [_tesseract(page) for page in pages]
    text = "\n\f\n".join(result.text for result in results)
    confidences = [result.confidence for result in results if result.confidence > 0]
    confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    return ExtractedText(text, confidence, "tesseract")


def _tesseract(path: Path) -> ExtractedText:
    executable = _require("tesseract", "tesseract-ocr tesseract-ocr-eng")
    result = _run([executable, str(path), "stdout", "-l", "eng", "--psm", "6", "tsv"])
    rows = list(csv.DictReader(io.StringIO(result.stdout), delimiter="\t"))
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    confidences: list[float] = []
    for row in rows:
        word = (row.get("text") or "").strip()
        if not word:
            continue
        key = tuple(row.get(name, "") for name in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(word)
        try:
            confidence = float(row.get("conf", "-1"))
        except ValueError:
            confidence = -1
        if confidence >= 0:
            confidences.append(confidence)
    text = "\n".join(" ".join(words) for words in lines.values())
    if not text.strip():
        raise LocalOcrError("Tesseract không tìm thấy chữ trong tài liệu.")
    confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    return ExtractedText(text, confidence, "tesseract")
