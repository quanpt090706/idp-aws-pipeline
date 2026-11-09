"""Parser for Amazon Textract AnalyzeExpense/StartExpenseAnalysis output."""

from __future__ import annotations

from typing import Any

from .common import (
    LOW_CONFIDENCE_THRESHOLD,
    average_confidence,
    detect_currency,
    make_warning,
    normalize_label,
    parse_date,
    parse_number,
)


SUMMARY_TYPE_MAP = {
    "VENDOR_NAME": "vendor_name",
    "RECEIVER_NAME": "vendor_name",
    "INVOICE_RECEIPT_ID": "invoice_number",
    "INVOICE_NUMBER": "invoice_number",
    "INVOICE_RECEIPT_DATE": "invoice_date",
    "INVOICE_DATE": "invoice_date",
    "SUBTOTAL": "subtotal",
    "TAX": "tax_amount",
    "TOTAL": "total_amount",
    "AMOUNT_DUE": "total_amount",
    "CURRENCY": "currency",
}

LABEL_ALIASES = {
    "vendor_name": ("vendor", "seller", "merchant", "supplier", "don vi ban", "nguoi ban"),
    "invoice_number": ("invoice number", "invoice no", "so hoa don", "receipt id"),
    "invoice_date": ("invoice date", "receipt date", "ngay hoa don", "ngay"),
    "subtotal": ("subtotal", "tam tinh", "cong tien hang"),
    "tax_amount": ("tax", "vat", "tien thue", "thue gtgt"),
    "total_amount": ("grand total", "total amount", "tong cong", "tong tien", "thanh tien"),
    "currency": ("currency", "tien te", "don vi tien"),
}

ITEM_TYPE_MAP = {
    "ITEM": "description",
    "DESCRIPTION": "description",
    "QUANTITY": "quantity",
    "UNIT_PRICE": "unit_price",
    "PRICE": "amount",
    "AMOUNT": "amount",
}

REQUIRED_FIELDS = ("vendor_name", "invoice_date", "total_amount")
NUMERIC_FIELDS = {"subtotal", "tax_amount", "total_amount"}


def parse_invoice(raw_response: dict[str, Any]) -> dict[str, Any]:
    """Convert raw Textract expense output into the shared normalized contract."""

    extracted: dict[str, Any] = {
        "vendor_name": None,
        "invoice_number": None,
        "invoice_date": None,
        "currency": None,
        "subtotal": None,
        "tax_amount": None,
        "total_amount": None,
        "items": [],
    }
    warnings: list[dict[str, Any]] = []
    field_confidences: dict[str, float] = {}
    currency_hints: list[str] = []
    item_confidences: list[float] = []

    expense_documents = raw_response.get("ExpenseDocuments") or []
    if not expense_documents:
        warnings.append(
            make_warning(
                "EMPTY_TEXTRACT_RESULT",
                "ExpenseDocuments",
                "Textract did not return any expense document.",
            )
        )

    for document in expense_documents:
        for summary_field in document.get("SummaryFields", []):
            field_name = _summary_field_name(summary_field)
            if not field_name:
                continue
            value_detection = summary_field.get("ValueDetection") or {}
            raw_value = str(value_detection.get("Text") or "").strip()
            if not raw_value:
                continue
            confidence = _confidence(value_detection, summary_field)
            if confidence <= field_confidences.get(field_name, -1):
                continue

            normalized_value = _normalize_summary_value(field_name, raw_value)
            if normalized_value is None and field_name in NUMERIC_FIELDS | {"invoice_date"}:
                warnings.append(
                    make_warning(
                        "INVALID_FIELD_VALUE",
                        field_name,
                        "The field could not be normalized safely.",
                        raw_value=raw_value,
                    )
                )
            else:
                extracted[field_name] = normalized_value
            field_confidences[field_name] = confidence
            currency_hints.append(raw_value)
            currency_code = value_detection.get("Currency", {}).get("Code")
            if currency_code:
                currency_hints.append(str(currency_code))

        for group in document.get("LineItemGroups", []):
            for line_item in group.get("LineItems", []):
                item, confidence, item_warnings = _parse_line_item(line_item)
                warnings.extend(item_warnings)
                if item is not None:
                    extracted["items"].append(item)
                    item_confidences.append(confidence)

    if not extracted["currency"]:
        extracted["currency"] = detect_currency(*currency_hints)

    for field_name in REQUIRED_FIELDS:
        if extracted[field_name] is None:
            warnings.append(
                make_warning(
                    "MISSING_REQUIRED_FIELD",
                    field_name,
                    "A required invoice field was not found.",
                )
            )
        elif field_confidences.get(field_name, 0.0) < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(
                make_warning(
                    "LOW_CONFIDENCE",
                    field_name,
                    "The required invoice field has low OCR confidence.",
                    confidence=round(field_confidences[field_name], 2),
                    threshold=LOW_CONFIDENCE_THRESHOLD,
                )
            )

    confidence_inputs = [field_confidences.get(field) for field in REQUIRED_FIELDS]
    confidence_inputs.extend(item_confidences)
    return {
        "document_type": "INVOICE",
        "confidence": average_confidence(confidence_inputs),
        "warnings": warnings,
        "extracted": extracted,
    }


def _summary_field_name(summary_field: dict[str, Any]) -> str | None:
    field_type = str((summary_field.get("Type") or {}).get("Text") or "").upper()
    if field_type in SUMMARY_TYPE_MAP:
        return SUMMARY_TYPE_MAP[field_type]

    label = normalize_label((summary_field.get("LabelDetection") or {}).get("Text"))
    for field_name, aliases in LABEL_ALIASES.items():
        if any(alias == label for alias in aliases):
            return field_name
    for field_name, aliases in LABEL_ALIASES.items():
        if any(alias in label for alias in aliases):
            return field_name
    return None


def _normalize_summary_value(field_name: str, raw_value: str) -> Any:
    if field_name == "invoice_date":
        return parse_date(raw_value)
    if field_name in NUMERIC_FIELDS:
        return parse_number(raw_value)
    if field_name == "currency":
        return detect_currency(raw_value) or raw_value.upper()
    return raw_value


def _parse_line_item(
    line_item: dict[str, Any],
) -> tuple[dict[str, Any] | None, float, list[dict[str, Any]]]:
    item: dict[str, Any] = {
        "description": None,
        "quantity": None,
        "unit_price": None,
        "amount": None,
        "confidence": 0.0,
    }
    warnings: list[dict[str, Any]] = []
    confidences: list[float] = []

    for expense_field in line_item.get("LineItemExpenseFields", []):
        field_type = str((expense_field.get("Type") or {}).get("Text") or "").upper()
        field_name = ITEM_TYPE_MAP.get(field_type)
        value_detection = expense_field.get("ValueDetection") or {}
        raw_value = str(value_detection.get("Text") or "").strip()
        if not field_name or not raw_value:
            continue
        value: Any = raw_value if field_name == "description" else parse_number(raw_value)
        if value is None:
            warnings.append(
                make_warning(
                    "INVALID_LINE_ITEM_VALUE",
                    f"items[].{field_name}",
                    "A line-item value could not be normalized.",
                    raw_value=raw_value,
                )
            )
            continue
        item[field_name] = value
        confidences.append(_confidence(value_detection, expense_field))

    if all(item[field] is None for field in ("description", "quantity", "unit_price", "amount")):
        warnings.append(
            make_warning(
                "EMPTY_LINE_ITEM",
                "items[]",
                "Textract returned a line-item group without usable fields.",
            )
        )
        return None, 0.0, warnings

    item["confidence"] = average_confidence(confidences)
    if item["description"] is None or item["amount"] is None:
        warnings.append(
            make_warning(
                "INCOMPLETE_LINE_ITEM",
                "items[]",
                "A line item is missing its description or amount.",
            )
        )
    if item["confidence"] < LOW_CONFIDENCE_THRESHOLD:
        warnings.append(
            make_warning(
                "LOW_CONFIDENCE",
                "items[]",
                "A line item has low OCR confidence.",
                confidence=item["confidence"],
                threshold=LOW_CONFIDENCE_THRESHOLD,
            )
        )
    return item, item["confidence"], warnings


def _confidence(primary: dict[str, Any], fallback: dict[str, Any]) -> float:
    value = primary.get("Confidence", fallback.get("Confidence", 0.0))
    return float(value or 0.0)
