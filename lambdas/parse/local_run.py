"""Small CLI for running a TV3 parser against a local Textract fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .parsers import parse_invoice, parse_transcript


Parser = Callable[[dict[str, Any]], dict[str, Any]]


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Parse a local raw Textract JSON fixture without AWS credentials."
    )
    argument_parser.add_argument("document_type", choices=("invoice", "transcript"))
    argument_parser.add_argument("fixture", type=Path)
    arguments = argument_parser.parse_args()

    parsers: dict[str, Parser] = {
        "invoice": parse_invoice,
        "transcript": parse_transcript,
    }
    with arguments.fixture.open(encoding="utf-8") as stream:
        raw_response = json.load(stream)
    print(json.dumps(parsers[arguments.document_type](raw_response), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
