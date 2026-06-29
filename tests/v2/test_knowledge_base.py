from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from app.v2.errors import InvalidWorkbookError
from app.v2.knowledge_base.step_02_loader import WorkbookLoader
from app.v2.knowledge_base.step_03_validator import WorkbookValidator
from app.v2.workflow.step_03_registry import WORKFLOW_HANDLER_METHODS

WORKBOOK = Path(
    os.getenv(
        "V2_TEST_WORKBOOK",
        "/home/ogier-derouineau/Downloads/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm",
    )
)


@unittest.skipUnless(WORKBOOK.is_file(), f"V2 test workbook not found: {WORKBOOK}")
class WorkbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = WorkbookLoader()
        self.validator = WorkbookValidator()

    def test_v5_loads_and_all_exact_joins_validate(self) -> None:
        snapshot = self.validator.validate(self.loader.load(WORKBOOK))
        self.assertEqual(snapshot.version.sha256, "6db9ba5d8ff8a43d20d8749076e33c9908a69d4a9b046bd95124671d7baac040")
        self.assertEqual(len(snapshot.workflow_steps), 19)
        self.assertEqual(len(snapshot.blueprint), 14)
        self.assertEqual(
            {row.step_key for row in snapshot.workflow_steps},
            set(WORKFLOW_HANDLER_METHODS),
        )
        event_story = next(row for row in snapshot.acf_fields if row.field_key == "event_story")
        self.assertEqual((event_story.min_words, event_story.max_words), (80, 100))

    def test_configured_fields_are_excluded_from_ai_schema(self) -> None:
        snapshot = self.validator.validate(self.loader.load(WORKBOOK))
        configured = [row for row in snapshot.shared_fields if row.source_mode == "configured"]
        self.assertTrue(configured)
        self.assertTrue(all(not row.include_in_ai_schema for row in configured))

    def test_duplicate_active_url_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "duplicate.xlsm"
            copy.write_bytes(WORKBOOK.read_bytes())
            workbook = load_workbook(copy, keep_vba=True)
            sheet = workbook["internal_links_database"]
            target_url_column = next(
                cell.column for cell in sheet[1] if cell.value == "target_url"
            )
            active_column = next(cell.column for cell in sheet[1] if cell.value == "active")
            sheet.cell(3, target_url_column).value = sheet.cell(2, target_url_column).value
            sheet.cell(3, active_column).value = True
            workbook.save(copy)
            with self.assertRaises(InvalidWorkbookError) as raised:
                self.validator.validate(self.loader.load(copy))
            codes = {detail.error_code for detail in raised.exception.details}
            self.assertIn("duplicate_active_url", codes)

    def test_unknown_source_fact_key_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "bad-source.xlsm"
            copy.write_bytes(WORKBOOK.read_bytes())
            workbook = load_workbook(copy, keep_vba=True)
            sheet = workbook["ACF_fields_schema"]
            field_key_column = next(cell.column for cell in sheet[1] if cell.value == "field_key")
            source_column = next(cell.column for cell in sheet[1] if cell.value == "source_fact_keys")
            row = next(
                index
                for index in range(2, sheet.max_row + 1)
                if sheet.cell(index, field_key_column).value == "fact_event"
            )
            sheet.cell(row, source_column).value = "not_a_fact"
            workbook.save(copy)
            with self.assertRaises(InvalidWorkbookError) as raised:
                self.validator.validate(self.loader.load(copy))
            codes = {detail.error_code for detail in raised.exception.details}
            self.assertIn("unknown_source_fact_key", codes)
