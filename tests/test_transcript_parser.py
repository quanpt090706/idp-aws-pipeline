from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from lambdas.parse import parse_transcript


FIXTURES = Path(__file__).parent / "fixtures"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


class TranscriptParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = load_json(FIXTURES / "textract" / "transcript.json")

    def test_parses_complete_transcript_fixture(self) -> None:
        expected = load_json(FIXTURES / "expected" / "transcript.json")

        self.assertEqual(parse_transcript(self.raw), expected)

    def test_missing_student_and_incomplete_subject_do_not_crash(self) -> None:
        raw = copy.deepcopy(self.raw)
        blocks = {block.get("Id"): block for block in raw["Blocks"]}
        for block_id in ("word-value-name-1", "word-value-name-2", "word-value-name-3"):
            blocks[block_id]["Text"] = ""
        blocks["word-34"]["Text"] = ""

        result = parse_transcript(raw)
        warning_pairs = {(warning["code"], warning["field"]) for warning in result["warnings"]}

        self.assertIsNone(result["extracted"]["student_name"])
        self.assertEqual(len(result["extracted"]["subjects"]), 2)
        self.assertIsNone(result["extracted"]["subjects"][1]["score"])
        self.assertIn(("MISSING_REQUIRED_FIELD", "student_name"), warning_pairs)
        self.assertIn(("MISSING_REQUIRED_FIELD", "subjects[1].score"), warning_pairs)

    def test_low_confidence_subject_cell_creates_warning(self) -> None:
        raw = copy.deepcopy(self.raw)
        score_word = next(block for block in raw["Blocks"] if block.get("Id") == "word-24")
        score_word["Confidence"] = 45.0

        result = parse_transcript(raw)
        warning_pairs = {(warning["code"], warning["field"]) for warning in result["warnings"]}

        self.assertIn(("LOW_CONFIDENCE", "subjects[0].score"), warning_pairs)


if __name__ == "__main__":
    unittest.main()
