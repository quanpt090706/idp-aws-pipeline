from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from lambdas.parse import parse_invoice
from lambdas.parse.parsers.common import parse_number


FIXTURES = Path(__file__).parent / "fixtures"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


class InvoiceParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = load_json(FIXTURES / "textract" / "invoice.json")

    def test_parses_complete_invoice_fixture(self) -> None:
        expected = load_json(FIXTURES / "expected" / "invoice.json")

        self.assertEqual(parse_invoice(self.raw), expected)

    def test_missing_and_low_confidence_fields_create_warnings(self) -> None:
        raw = copy.deepcopy(self.raw)
        fields = raw["ExpenseDocuments"][0]["SummaryFields"]
        raw["ExpenseDocuments"][0]["SummaryFields"] = [
            field
            for field in fields
            if field["Type"]["Text"] != "INVOICE_RECEIPT_DATE"
        ]
        vendor = next(field for field in fields if field["Type"]["Text"] == "VENDOR_NAME")
        vendor["ValueDetection"]["Confidence"] = 55.0

        result = parse_invoice(raw)
        warning_pairs = {(warning["code"], warning["field"]) for warning in result["warnings"]}

        self.assertIsNone(result["extracted"]["invoice_date"])
        self.assertIn(("MISSING_REQUIRED_FIELD", "invoice_date"), warning_pairs)
        self.assertIn(("LOW_CONFIDENCE", "vendor_name"), warning_pairs)

    def test_number_normalization_supports_common_locales(self) -> None:
        cases = {
            "450.000 VND": 450000,
            "15,400,000": 15400000,
            "$1,234.56": 1234.56,
            "1.234,56 EUR": 1234.56,
            "8,5": 8.5,
        }

        for raw_value, expected in cases.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(parse_number(raw_value), expected)


if __name__ == "__main__":
    unittest.main()
