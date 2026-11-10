"""Best-effort English invoice parser for temporary local OCR mode."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from lambdas.parse.parsers.common import detect_currency, make_warning, parse_number


DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|"
    r"\d{1,2}[ -](?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)[, -]+\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{2,4})\b",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(r"(?:USD|EUR|VND|[$€₫])?\s*-?\d[\d,.]*")
INVOICE_NUMBER_PATTERN = re.compile(
    r"\binvoice\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{2,})",
    re.IGNORECASE,
)


def parse_invoice_text(text: str, ocr_confidence: float = 90.0) -> dict[str, Any]:
    """Return the same normalized shape as the Amazon Textract parser."""

    raw_lines = [line.rstrip() for line in text.replace("\r", "").split("\n")]
    lines = [line.strip() for line in raw_lines if line.strip()]
    extracted: dict[str, Any] = {
        "vendor_name": _vendor(lines),
        "invoice_number": _invoice_number(lines),
        "invoice_date": _invoice_date(lines),
        "currency": detect_currency(text),
        "subtotal": _labelled_amount(lines, (r"\bsub\s*total\b",)),
        "tax_amount": _labelled_amount(lines, (r"\bsales\s+tax\b", r"\btax\b", r"\bvat\b")),
        "total_amount": _labelled_amount(
            lines,
            (r"\bgrand\s+total\b", r"\btotal\s+due\b", r"\bamount\s+due\b", r"^total\b"),
        ),
        "items": _items(raw_lines, ocr_confidence),
    }
    if not extracted["currency"]:
        extracted["currency"] = "USD" if "$" in text else None

    warnings: list[dict[str, Any]] = []
    for field in ("vendor_name", "invoice_date", "total_amount"):
        if extracted[field] is None:
            warnings.append(
                make_warning(
                    "MISSING_REQUIRED_FIELD",
                    field,
                    "Local OCR could not find a required invoice field.",
                )
            )
    if not extracted["items"]:
        warnings.append(
            make_warning(
                "NO_LINE_ITEMS",
                "items",
                "Local OCR did not identify invoice line items; verify the totals manually.",
            )
        )
    if ocr_confidence < 80:
        warnings.append(
            make_warning(
                "LOW_CONFIDENCE",
                "document",
                "The local OCR engine reported low text confidence.",
                confidence=round(ocr_confidence, 2),
                threshold=80,
            )
        )

    present_required = sum(extracted[field] is not None for field in ("vendor_name", "invoice_date", "total_amount"))
    completeness = present_required / 3
    confidence = round(min(float(ocr_confidence), 95.0) * completeness, 2)
    return {
        "document_type": "INVOICE",
        "confidence": confidence,
        "warnings": warnings,
        "extracted": extracted,
    }


def _vendor(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = re.match(r"from\s*:\s*(.+)$", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        if re.fullmatch(r"from\s*:?", line, re.IGNORECASE) and index + 1 < len(lines):
            return lines[index + 1].strip()

    for line in lines[:8]:
        candidate = re.sub(r"\binvoice\b", "", line, flags=re.IGNORECASE).strip(" :-")
        if not candidate:
            continue
        if DATE_PATTERN.search(candidate) or re.search(r"invoice\s*(?:#|no|number)", line, re.IGNORECASE):
            continue
        if re.search(r"(?:\b(?:sub\s*total|grand\s+total|total\s+due|amount\s+due|tax|vat)\b|^total\b)", candidate, re.IGNORECASE):
            continue
        if re.fullmatch(r"(?:date|bill to|ship to|from|to)\s*:?", candidate, re.IGNORECASE):
            continue
        return candidate
    return None


def _invoice_number(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = INVOICE_NUMBER_PATTERN.search(line)
        if match:
            return match.group(1)
        if re.search(r"invoice\s+(?:number|no\.?)", line, re.IGNORECASE) and index + 1 < len(lines):
            following = DATE_PATTERN.sub(" ", lines[index + 1])
            candidates = re.findall(r"\b[A-Z0-9][A-Z0-9-]{2,}\b", following, re.IGNORECASE)
            if candidates:
                return candidates[-1]
    return None


def _invoice_date(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if not re.search(r"\b(?:invoice\s+)?date\b", line, re.IGNORECASE):
            continue
        match = DATE_PATTERN.search(line)
        if not match and index + 1 < len(lines):
            match = DATE_PATTERN.search(lines[index + 1])
        if match:
            return _normalise_date(match.group(0))
    return None


def _normalise_date(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", value.strip().replace(",", ""))
    formats = (
        "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y",
        "%b %d %Y", "%B %d %Y", "%d/%m/%Y", "%m/%d/%Y",
        "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y",
    )
    for date_format in formats:
        try:
            return datetime.strptime(candidate, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _labelled_amount(lines: list[str], labels: tuple[str, ...]) -> int | float | None:
    for label in labels:
        pattern = re.compile(label, re.IGNORECASE)
        for line in reversed(lines):
            match = pattern.search(line)
            if not match:
                continue
            if "subtotal" not in label.replace("\\s*", "") and re.search(r"sub\s*total", line, re.IGNORECASE):
                continue
            amounts = AMOUNT_PATTERN.findall(line[match.end():])
            values = [parse_number(amount) for amount in amounts]
            usable = [value for value in values if value is not None]
            if usable:
                return usable[-1]
    return None


def _items(raw_lines: list[str], confidence: float) -> list[dict[str, Any]]:
    header_index = next(
        (
            index for index, line in enumerate(raw_lines)
            if re.search(r"description|service", line, re.IGNORECASE)
            and re.search(r"amount|line\s+total", line, re.IGNORECASE)
        ),
        None,
    )
    if header_index is None:
        return []

    items: list[dict[str, Any]] = []
    for line in raw_lines[header_index + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\b(?:sub\s*total|grand\s+total|sales\s+tax|total\s+due|tax)\b", stripped, re.IGNORECASE):
            break
        columns = [column.strip() for column in re.split(r"\s{2,}", stripped) if column.strip()]
        if len(columns) < 3:
            continue
        amount_positions = [index for index, column in enumerate(columns) if parse_number(column) is not None and re.search(r"[$€₫,.]", column)]
        if not amount_positions:
            continue
        amount_index = amount_positions[-1]
        amount = parse_number(columns[amount_index])
        unit_price = parse_number(columns[amount_positions[-2]]) if len(amount_positions) > 1 else None
        prefix = columns[:amount_positions[0]]
        quantity = None
        if prefix and re.fullmatch(r"\d+(?:[.,]\d+)?", prefix[0]):
            quantity = parse_number(prefix.pop(0))
        elif prefix and re.fullmatch(r"\d+(?:[.,]\d+)?", prefix[-1]):
            quantity = parse_number(prefix.pop())
        description = " ".join(prefix).strip() or None
        if description is None or amount is None:
            continue
        items.append({
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "amount": amount,
            "confidence": round(min(float(confidence), 95.0), 2),
        })
    return items
