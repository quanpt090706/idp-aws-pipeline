"""Local-only OCR adapter that preserves the application's output contract."""

from .invoice_text import parse_invoice_text

__all__ = ["parse_invoice_text"]
