"""Parser for Textract StartDocumentAnalysis(TABLES, FORMS) output."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .common import (
    LOW_CONFIDENCE_THRESHOLD,
    average_confidence,
    block_text,
    make_warning,
    normalize_label,
    parse_number,
    relationship_ids,
)


STUDENT_FIELD_ALIASES = {
    "student_id": ("student id", "student code", "ma sinh vien", "ma sv", "mssv"),
    "student_name": ("student name", "full name", "ho va ten", "ho ten", "sinh vien"),
    "school_name": ("school", "university", "institution", "truong", "ten truong"),
    "academic_year": ("academic year", "school year", "nam hoc", "khoa hoc"),
    "gpa": ("gpa", "grade point average", "diem trung binh", "dtb"),
}

HEADER_ALIASES = {
    "code": ("ma mon", "ma hoc phan", "ma mh", "course code", "subject code"),
    "name": ("ten mon", "ten hoc phan", "mon hoc", "course name", "subject name"),
    "credits": ("tin chi", "so tc", "credits", "credit"),
    "score": ("diem tong ket", "diem mon", "diem", "score", "numeric grade"),
    "letter_grade": ("diem chu", "xep loai", "letter grade"),
}

REQUIRED_STUDENT_FIELDS = ("student_id", "student_name")
REQUIRED_SUBJECT_FIELDS = ("code", "name", "score")


def parse_transcript(raw_response: dict[str, Any]) -> dict[str, Any]:
    """Convert raw Textract document blocks into the transcript contract."""

    blocks = raw_response.get("Blocks") or []
    block_map = {str(block["Id"]): block for block in blocks if block.get("Id")}
    warnings: list[dict[str, Any]] = []
    extracted: dict[str, Any] = {
        "student_id": None,
        "student_name": None,
        "school_name": None,
        "academic_year": None,
        "gpa": None,
        "subjects": [],
    }
    student_confidences: dict[str, float] = {}

    kv_values = _extract_key_values(blocks, block_map)
    for key, value, confidence in kv_values:
        field_name = _match_alias(key, STUDENT_FIELD_ALIASES)
        if not field_name or confidence <= student_confidences.get(field_name, -1):
            continue
        normalized_value: Any = parse_number(value) if field_name == "gpa" else value.strip()
        if normalized_value in {None, ""}:
            continue
        extracted[field_name] = normalized_value
        student_confidences[field_name] = confidence

    _apply_line_fallback(blocks, extracted, student_confidences)
    subjects, subject_confidences, table_warnings = _extract_subjects(blocks, block_map)
    extracted["subjects"] = subjects
    warnings.extend(table_warnings)

    for field_name in REQUIRED_STUDENT_FIELDS:
        if extracted[field_name] is None:
            warnings.append(
                make_warning(
                    "MISSING_REQUIRED_FIELD",
                    field_name,
                    "A required student field was not found.",
                )
            )
        elif student_confidences.get(field_name, 0.0) < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(
                make_warning(
                    "LOW_CONFIDENCE",
                    field_name,
                    "The required student field has low OCR confidence.",
                    confidence=round(student_confidences[field_name], 2),
                    threshold=LOW_CONFIDENCE_THRESHOLD,
                )
            )

    if not subjects:
        warnings.append(
            make_warning(
                "MISSING_REQUIRED_FIELD",
                "subjects",
                "No valid transcript subject row was found.",
            )
        )

    confidence_inputs = [student_confidences.get(field) for field in REQUIRED_STUDENT_FIELDS]
    confidence_inputs.extend(subject_confidences)
    return {
        "document_type": "TRANSCRIPT",
        "confidence": average_confidence(confidence_inputs),
        "warnings": warnings,
        "extracted": extracted,
    }


def _extract_key_values(
    blocks: list[dict[str, Any]],
    block_map: dict[str, dict[str, Any]],
) -> list[tuple[str, str, float]]:
    results: list[tuple[str, str, float]] = []
    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET" or "KEY" not in block.get("EntityTypes", []):
            continue
        key_text, key_confidence = block_text(block, block_map)
        for value_id in relationship_ids(block, "VALUE"):
            value_block = block_map.get(value_id, {})
            value_text, value_confidence = block_text(value_block, block_map)
            if key_text and value_text:
                results.append(
                    (
                        key_text,
                        value_text,
                        average_confidence((key_confidence, value_confidence)),
                    )
                )
    return results


def _apply_line_fallback(
    blocks: list[dict[str, Any]],
    extracted: dict[str, Any],
    confidences: dict[str, float],
) -> None:
    for block in blocks:
        if block.get("BlockType") != "LINE" or not block.get("Text"):
            continue
        line = str(block["Text"]).strip()
        normalized_line = normalize_label(line)
        for field_name, aliases in STUDENT_FIELD_ALIASES.items():
            if extracted[field_name] is not None:
                continue
            matching_alias = next(
                (alias for alias in aliases if normalized_line.startswith(alias + " ") or normalized_line == alias),
                None,
            )
            if not matching_alias:
                continue
            parts = re.split(r"\s*[:\-]\s*", line, maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                continue
            value: Any = parse_number(parts[1]) if field_name == "gpa" else parts[1].strip()
            if value is not None:
                extracted[field_name] = value
                confidences[field_name] = float(block.get("Confidence") or 0.0)


def _extract_subjects(
    blocks: list[dict[str, Any]],
    block_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[float], list[dict[str, Any]]]:
    subjects: list[dict[str, Any]] = []
    required_confidences: list[float] = []
    warnings: list[dict[str, Any]] = []

    for table in (block for block in blocks if block.get("BlockType") == "TABLE"):
        rows = _table_rows(table, block_map)
        header_row_number, header_map = _find_header(rows)
        if header_row_number is None:
            continue

        for row_number in sorted(rows):
            if row_number <= header_row_number:
                continue
            row = rows[row_number]
            if _recognized_header_count(row) >= 2:
                continue
            if not any(text.strip() for text, _ in row.values()):
                continue

            subject: dict[str, Any] = {
                "code": None,
                "name": None,
                "credits": None,
                "score": None,
                "letter_grade": None,
                "confidence": 0.0,
            }
            field_confidences: dict[str, float] = {}
            for column_number, field_name in header_map.items():
                text, confidence = row.get(column_number, ("", 0.0))
                if not text.strip():
                    continue
                value: Any = text.strip()
                if field_name in {"credits", "score"}:
                    value = parse_number(value)
                    if value is None:
                        warnings.append(
                            make_warning(
                                "INVALID_SUBJECT_VALUE",
                                f"subjects[{len(subjects)}].{field_name}",
                                "A transcript cell could not be normalized as a number.",
                                raw_value=text,
                                row=row_number,
                            )
                        )
                        continue
                subject[field_name] = value
                field_confidences[field_name] = confidence

            if all(subject[field] is None for field in REQUIRED_SUBJECT_FIELDS):
                continue

            subject["confidence"] = average_confidence(field_confidences.values())
            subject_index = len(subjects)
            for field_name in REQUIRED_SUBJECT_FIELDS:
                field_path = f"subjects[{subject_index}].{field_name}"
                if subject[field_name] is None:
                    warnings.append(
                        make_warning(
                            "MISSING_REQUIRED_FIELD",
                            field_path,
                            "A subject row is missing a required field.",
                            row=row_number,
                        )
                    )
                else:
                    required_confidences.append(field_confidences.get(field_name, 0.0))
                    if field_confidences.get(field_name, 0.0) < LOW_CONFIDENCE_THRESHOLD:
                        warnings.append(
                            make_warning(
                                "LOW_CONFIDENCE",
                                field_path,
                                "A required subject field has low OCR confidence.",
                                confidence=round(field_confidences.get(field_name, 0.0), 2),
                                threshold=LOW_CONFIDENCE_THRESHOLD,
                                row=row_number,
                            )
                        )
            subjects.append(subject)

    return subjects, required_confidences, warnings


def _table_rows(
    table: dict[str, Any],
    block_map: dict[str, dict[str, Any]],
) -> dict[int, dict[int, tuple[str, float]]]:
    rows: dict[int, dict[int, tuple[str, float]]] = defaultdict(dict)
    for cell_id in relationship_ids(table, "CHILD"):
        cell = block_map.get(cell_id, {})
        if cell.get("BlockType") not in {"CELL", "MERGED_CELL"}:
            continue
        row_number = int(cell.get("RowIndex") or 0)
        column_number = int(cell.get("ColumnIndex") or 0)
        if row_number <= 0 or column_number <= 0:
            continue
        rows[row_number][column_number] = block_text(cell, block_map)
    return dict(rows)


def _find_header(
    rows: dict[int, dict[int, tuple[str, float]]],
) -> tuple[int | None, dict[int, str]]:
    for row_number in sorted(rows):
        header_map: dict[int, str] = {}
        for column_number, (text, _) in rows[row_number].items():
            field_name = _match_alias(text, HEADER_ALIASES)
            if field_name:
                header_map[column_number] = field_name
        recognized = set(header_map.values())
        if len(recognized) >= 3 and {"code", "name", "score"}.issubset(recognized):
            return row_number, header_map
    return None, {}


def _recognized_header_count(row: dict[int, tuple[str, float]]) -> int:
    return sum(1 for text, _ in row.values() if _match_alias(text, HEADER_ALIASES))


def _match_alias(value: str, aliases_by_field: dict[str, tuple[str, ...]]) -> str | None:
    normalized = normalize_label(value)
    for field_name, aliases in aliases_by_field.items():
        if any(normalized == alias for alias in aliases):
            return field_name
    for field_name, aliases in aliases_by_field.items():
        if any(normalized.startswith(alias + " ") for alias in aliases):
            return field_name
    return None
