from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from app.v2.content_generation.step_01_schema_factory import (
    build_generation_model,
    build_image_analysis_model,
)
from app.v2.images.step_02_processor import PillowProcessor
from app.v2.knowledge_base.step_02_loader import WorkbookLoader
from app.v2.knowledge_base.step_03_validator import WorkbookValidator

WORKBOOK = Path(
    os.getenv(
        "V2_TEST_WORKBOOK",
        "/home/ogier-derouineau/Documents/FLAIRLAB_Knowledge_Base_Revised_V6.xlsm",
    )
)


@unittest.skipUnless(WORKBOOK.is_file(), f"V2 test workbook not found: {WORKBOOK}")
class GenerationAndImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = WorkbookValidator().validate(WorkbookLoader().load(WORKBOOK))

    def test_structured_schema_rejects_unknown_fields(self) -> None:
        row = next(item for item in self.snapshot.shared_fields if item.field_key == "post_title")
        model = build_generation_model([row], name="PostTitleResponse")
        with self.assertRaises(ValidationError):
            model.model_validate({"post_title": "Valid title", "invented": "bad"})

    def test_optional_fields_are_required_nullable_for_openai_strict_schema(self) -> None:
        row = next(item for item in self.snapshot.acf_fields if item.field_key == "fact_bar")
        model = build_generation_model([row], name="OptionalFactResponse")
        schema = model.model_json_schema()
        self.assertIn("fact_bar", schema["required"])
        self.assertIsNone(model.model_validate({"fact_bar": None}).fact_bar)

    def test_word_limits_are_enforced(self) -> None:
        row = next(item for item in self.snapshot.acf_fields if item.field_key == "event_story")
        model = build_generation_model([row], name="EventStoryResponse")
        with self.assertRaises(ValidationError):
            model.model_validate({"event_story": "too short"})

    def test_word_limits_are_visible_in_structured_schema(self) -> None:
        row = next(item for item in self.snapshot.acf_fields if item.field_key == "event_story")
        model = build_generation_model([row], name="EventStoryResponse")
        description = model.model_json_schema()["properties"]["event_story"]["description"]
        self.assertIn("Minimum 80 words.", description)
        self.assertIn("Maximum 100 words.", description)

    def test_aggregation_source_rejects_model_html(self) -> None:
        row = next(item for item in self.snapshot.acf_fields if item.field_key == "fact_event")
        model = build_generation_model([row], name="RawAggregationResponse")
        with self.assertRaises(ValidationError):
            model.model_validate(
                {"fact_event": "<li><strong>Event:</strong> Sommerfest</li>"}
            )

    def test_image_analysis_schema_is_strict_for_nested_objects(self) -> None:
        enum_families = {
            family: tuple(self.snapshot.validation_family(family))
            for family in {
                row.output_domain
                for row in self.snapshot.image_analysis_rules
                if row.output_domain
            }
        }
        model = build_image_analysis_model(
            list(self.snapshot.image_analysis_rules),
            enum_families=enum_families,
        )
        schema = model.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        boolean_def = schema["$defs"]["BooleanWithReason"]
        focal_def = schema["$defs"]["NormalizedFocalPoint"]
        self.assertFalse(boolean_def["additionalProperties"])
        self.assertFalse(focal_def["additionalProperties"])
        enum_list_rows = [
            row for row in self.snapshot.image_analysis_rules
            if row.enabled and row.expected_output == "enum_list"
        ]
        self.assertTrue(enum_list_rows)
        for row in enum_list_rows:
            self.assertEqual(schema["properties"][row.analysis_key]["type"], "array")

    def test_pillow_values_come_from_workbook_and_original_survives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "processed.webp"
            Image.new("RGB", (640, 480), "navy").save(source)
            original_bytes = source.read_bytes()
            result = PillowProcessor().process(
                self.snapshot,
                source=source,
                destination=output,
                analysis={"brightness_score": 80, "noise_score": 0},
            )
            self.assertTrue(output.is_file())
            self.assertLessEqual(output.stat().st_size, 50 * 1024)
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(result["format"], "WEBP")
            self.assertIn("operations", result)

    def test_pillow_uses_vision_crop_feedback_and_reports_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "processed.webp"
            Image.new("RGB", (1200, 600), "navy").save(source)
            result = PillowProcessor().process(
                self.snapshot,
                source=source,
                destination=output,
                analysis={
                    "brightness_score": 30,
                    "noise_score": 25,
                    "crop_recommendation": {"x": 0.82, "y": 0.35},
                },
            )
            self.assertTrue(output.is_file())
            operations = "\n".join(result["operations"])
            self.assertIn("vision.crop_recommendation focal_x=0.82, focal_y=0.35", operations)
            self.assertIn("enhance.brightness_factor", operations)
            self.assertIn("filter.median_size", operations)
            self.assertIn("crop.aspect_ratio=4:3", operations)

    def test_pillow_keeps_minimum_quality_when_target_size_is_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "processed.webp"
            Image.new("RGB", (1800, 1200), "navy").save(source)
            result = PillowProcessor().process(
                self.snapshot,
                source=source,
                destination=output,
                analysis={},
            )
            self.assertTrue(output.is_file())
            self.assertIn("target_reached", result)
            if not result["target_reached"]:
                self.assertTrue(result["warnings"])

    def test_pillow_target_saver_returns_warning_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tiny.webp"
            result = PillowProcessor._save_to_target(
                Image.new("RGB", (64, 64), "navy"),
                output,
                output_format="WEBP",
                target_bytes=1,
                quality=80,
                minimum_quality=80,
                quality_step=10,
            )
            self.assertTrue(output.is_file())
            self.assertFalse(result["target_reached"])
            self.assertTrue(result["warnings"])
