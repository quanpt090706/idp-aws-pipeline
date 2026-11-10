import unittest

from tools.local_ocr.invoice_text import parse_invoice_text


INVOICE_TEXT = """
ABC Private Limited
INVOICE # 123PQR456
DATE 01-Jan-2021

Description                 Quantity   Unit Price   Amount
Product 1                   1          $1000        $1000
Service 3                              $2789        $2789

Tax                                                $61.69
Grand Total                                        $3849.69
"""


class InvoiceTextParserTest(unittest.TestCase):
    def test_parses_real_text_instead_of_returning_demo_fixture(self):
        result = parse_invoice_text(INVOICE_TEXT, 92.5)

        self.assertEqual(result["document_type"], "INVOICE")
        self.assertEqual(result["extracted"], {
            "vendor_name": "ABC Private Limited",
            "invoice_number": "123PQR456",
            "invoice_date": "2021-01-01",
            "currency": "USD",
            "subtotal": None,
            "tax_amount": 61.69,
            "total_amount": 3849.69,
            "items": [
                {
                    "description": "Product 1",
                    "quantity": 1,
                    "unit_price": 1000,
                    "amount": 1000,
                    "confidence": 92.5,
                },
                {
                    "description": "Service 3",
                    "quantity": None,
                    "unit_price": 2789,
                    "amount": 2789,
                    "confidence": 92.5,
                },
            ],
        })
        self.assertEqual(result["warnings"], [])

    def test_missing_fields_and_low_ocr_confidence_require_review(self):
        result = parse_invoice_text("INVOICE\nTotal $10.00", 55.0)
        warning_codes = {warning["code"] for warning in result["warnings"]}

        self.assertEqual(result["extracted"]["total_amount"], 10)
        self.assertEqual(result["confidence"], 18.33)
        self.assertTrue({"MISSING_REQUIRED_FIELD", "NO_LINE_ITEMS", "LOW_CONFIDENCE"} <= warning_codes)


if __name__ == "__main__":
    unittest.main()
