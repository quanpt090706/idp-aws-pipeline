"""Shared normalization helpers for the offline Textract parsers."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


LOW_CONFIDENCE_THRESHOLD = 80.0


def normalize_label(value: str | None) -> str:
    """Return an accent-free, lower-case label suitable for alias matching."""

    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", value)
    without_accents = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", without_accents).lower().split())


def average_confidence(values: Iterable[float | int | None]) -> float:
    usable = [float(value) for value in values if value is not None]
    return round(sum(usable) / len(usable), 2) if usable else 0.0


def make_warning(
    code: str,
    field: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "field": field, "message": message}
    result.update({key: value for key, value in details.items() if value is not None})
    return result


def parse_date(value: str | None) -> str | None:
    """Normalize common unambiguous invoice dates to ISO 8601."""

    if not value:
        return None
    candidate = value.strip()
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d-%m-%y",
    )
    for date_format in formats:
        try:
            return datetime.strptime(candidate, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def parse_number(value: str | int | float | Decimal | None) -> int | float | None:
    """Parse Vietnamese/English thousands and decimal separators deterministically."""

    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        candidate = re.sub(r"[^0-9,\.\-]", "", str(value).strip())
        if not candidate or candidate in {"-", ".", ","}:
            return None
        candidate = _normalize_numeric_separators(candidate)
        try:
            number = Decimal(candidate)
        except InvalidOperation:
            return None

    if not number.is_finite():
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _normalize_numeric_separators(candidate: str) -> str:
    dot_count = candidate.count(".")
    comma_count = candidate.count(",")

    if dot_count and comma_count:
        decimal_separator = "." if candidate.rfind(".") > candidate.rfind(",") else ","
        thousands_separator = "," if decimal_separator == "." else "."
        candidate = candidate.replace(thousands_separator, "")
        return candidate.replace(decimal_separator, ".")

    separator = "." if dot_count else "," if comma_count else None
    if separator is None:
        return candidate

    parts = candidate.split(separator)
    if len(parts) > 2:
        if all(len(part) == 3 for part in parts[1:]):
            return "".join(parts)
        return "".join(parts[:-1]) + "." + parts[-1]

    integer_part, fractional_part = parts
    if len(fractional_part) == 3 and integer_part not in {"", "-"}:
        return integer_part + fractional_part
    return integer_part + "." + fractional_part


def detect_currency(*values: str | None) -> str | None:
    combined = " ".join(value or "" for value in values)
    upper = combined.upper()
    if re.search(r"\b(VND|VNĐ)\b", upper) or "₫" in combined:
        return "VND"
    if "$" in combined or re.search(r"\bUSD\b", upper):
        return "USD"
    if "€" in combined or re.search(r"\bEUR\b", upper):
        return "EUR"
    return None


def relationship_ids(block: dict[str, Any], relationship_type: str) -> list[str]:
    for relationship in block.get("Relationships", []):
        if relationship.get("Type") == relationship_type:
            return list(relationship.get("Ids", []))
    return []


def block_text(
    block: dict[str, Any],
    block_map: dict[str, dict[str, Any]],
) -> tuple[str, float | None]:
    """Read text and word confidence from a Textract block and its CHILD blocks."""

    direct_text = block.get("Text")
    child_ids = relationship_ids(block, "CHILD")
    words: list[str] = []
    confidences: list[float] = []
    for child_id in child_ids:
        child = block_map.get(child_id, {})
        block_type = child.get("BlockType")
        if block_type == "WORD" and child.get("Text"):
            words.append(str(child["Text"]))
            if child.get("Confidence") is not None:
                confidences.append(float(child["Confidence"]))
        elif block_type == "SELECTION_ELEMENT" and child.get("SelectionStatus") == "SELECTED":
            words.append("X")
            if child.get("Confidence") is not None:
                confidences.append(float(child["Confidence"]))

    text = " ".join(words).strip() or str(direct_text or "").strip()
    confidence: float | None
    if confidences:
        confidence = average_confidence(confidences)
    elif block.get("Confidence") is not None:
        confidence = float(block["Confidence"])
    else:
        confidence = None
    return text, confidence
