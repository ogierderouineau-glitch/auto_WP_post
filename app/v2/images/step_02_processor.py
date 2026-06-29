from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.v2.images.step_01_conditions import (
    ImageConditionContext,
    image_condition_matches,
)
from app.v2.knowledge_base.step_01_models import PillowRule, WorkbookSnapshot


class PillowProcessor:
    """Apply configured Pillow rules; numeric behavior comes from the workbook."""

    def process(
        self,
        snapshot: WorkbookSnapshot,
        *,
        source: Path,
        destination: Path,
        analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rules = sorted(
            (row for row in snapshot.pillow_rules if row.enabled),
            key=lambda row: (-row.numeric_priority, row.rule_key),
        )
        values = {row.rule_key: row.value for row in rules}
        values, operations = self._values_with_analysis(values, analysis or {})
        destination.parent.mkdir(parents=True, exist_ok=True)
        original_backup = destination.parent / f"{destination.stem}.original{source.suffix.lower()}"
        if not original_backup.exists():
            shutil.copy2(source, original_backup)
        try:
            with Image.open(source) as opened:
                image = opened.copy()
            context = ImageConditionContext(
                width=image.width,
                height=image.height,
                filesize_bytes=source.stat().st_size,
                values=values,
                analysis=analysis or {},
            )
            for rule in rules:
                if image_condition_matches(rule.condition, context, rule.value):
                    before = image
                    image = self._apply(image, rule, values)
                    if self._operation_is_visible(rule.rule_key) and image is not before:
                        operations.append(self._operation_label(rule, values))
                    context = ImageConditionContext(
                        width=image.width,
                        height=image.height,
                        filesize_bytes=context.filesize_bytes,
                        values=values,
                        analysis=context.analysis,
                    )
            output_format = str(values["output.format"]).upper()
            target_kb = int(values["compression.target_kb"])
            quality = int(values["compression.quality_start"])
            minimum_quality = int(values["compression.quality_min"])
            quality_step = int(values["compression.quality_step"])
            compression = self._save_to_target(
                image,
                destination,
                output_format=output_format,
                target_bytes=target_kb * 1024,
                quality=quality,
                minimum_quality=minimum_quality,
                quality_step=quality_step,
            )
            return {
                "source": str(source),
                "original_backup": str(original_backup),
                "output": str(destination),
                "size_bytes": destination.stat().st_size,
                "width": image.width,
                "height": image.height,
                "format": output_format,
                "operations": operations,
                **compression,
            }
        except Exception:
            if destination.exists():
                destination.unlink()
            raise

    @classmethod
    def _values_with_analysis(
        cls,
        values: dict[str, Any],
        analysis: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        dynamic_values = dict(values)
        operations: list[str] = []
        crop = analysis.get("crop_recommendation")
        if isinstance(crop, dict):
            x = cls._normalized_float(crop.get("x"))
            y = cls._normalized_float(crop.get("y"))
            if x is not None and y is not None:
                dynamic_values["crop.focal_x"] = x
                dynamic_values["crop.focal_y"] = y
                operations.append(f"vision.crop_recommendation focal_x={x:.2f}, focal_y={y:.2f}")
        if float(analysis.get("brightness_score", 100) or 100) < 45:
            operations.append("vision.image_dark -> brightness/shadow rules enabled")
        if float(analysis.get("noise_score", 0) or 0) > 20:
            operations.append("vision.noise_score_gt_20 -> median filter enabled")
        return dynamic_values, operations

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if 0 <= parsed <= 1:
            return parsed
        return None

    @staticmethod
    def _operation_is_visible(rule_key: str) -> bool:
        return (
            rule_key.startswith("prepare.")
            or rule_key.startswith("resize.")
            or rule_key.startswith("enhance.")
            or rule_key.startswith("filter.")
            or rule_key == "crop.aspect_ratio"
        )

    @staticmethod
    def _operation_label(rule: PillowRule, values: dict[str, Any]) -> str:
        if rule.rule_key == "crop.aspect_ratio":
            return (
                f"{rule.rule_key}={rule.value} "
                f"(focal_x={float(values.get('crop.focal_x', 0.5)):.2f}, "
                f"focal_y={float(values.get('crop.focal_y', 0.5)):.2f})"
            )
        return f"{rule.rule_key}={rule.value}"

    @staticmethod
    def _apply(image: Image.Image, rule: PillowRule, values: dict[str, Any]) -> Image.Image:
        if rule.rule_key == "prepare.auto_orient" and rule.value:
            return ImageOps.exif_transpose(image)
        if rule.rule_key == "resize.max_width" and image.width > int(rule.value):
            ratio = int(rule.value) / image.width
            return image.resize((int(rule.value), round(image.height * ratio)), Image.Resampling.LANCZOS)
        if rule.rule_key == "resize.max_height" and image.height > int(rule.value):
            ratio = int(rule.value) / image.height
            return image.resize((round(image.width * ratio), int(rule.value)), Image.Resampling.LANCZOS)
        if rule.rule_key == "enhance.brightness_factor":
            return ImageEnhance.Brightness(image).enhance(float(rule.value))
        if rule.rule_key == "enhance.contrast_factor":
            return ImageEnhance.Contrast(image).enhance(float(rule.value))
        if rule.rule_key == "enhance.color_factor":
            return ImageEnhance.Color(image).enhance(float(rule.value))
        if rule.rule_key == "enhance.sharpness_factor":
            return ImageEnhance.Sharpness(image).enhance(float(rule.value))
        if rule.rule_key == "enhance.shadow_gamma":
            gamma = float(rule.value)
            return image.point(lambda pixel: 255 * ((pixel / 255) ** gamma))
        if rule.rule_key == "filter.median_size":
            return image.filter(ImageFilter.MedianFilter(size=int(rule.value)))
        if rule.rule_key == "crop.aspect_ratio" and values.get("crop.mode") == "cover":
            width_ratio, height_ratio = (float(part) for part in str(rule.value).split(":", 1))
            target_ratio = width_ratio / height_ratio
            current_ratio = image.width / image.height
            focal_x = float(values.get("crop.focal_x", 0.5))
            focal_y = float(values.get("crop.focal_y", 0.5))
            if current_ratio > target_ratio:
                crop_width = round(image.height * target_ratio)
                left = round((image.width - crop_width) * focal_x)
                left = max(0, min(left, image.width - crop_width))
                return image.crop((left, 0, left + crop_width, image.height))
            crop_height = round(image.width / target_ratio)
            top = round((image.height - crop_height) * focal_y)
            top = max(0, min(top, image.height - crop_height))
            return image.crop((0, top, image.width, top + crop_height))
        return image

    @staticmethod
    def _save_to_target(
        image: Image.Image,
        destination: Path,
        *,
        output_format: str,
        target_bytes: int,
        quality: int,
        minimum_quality: int,
        quality_step: int,
    ) -> dict[str, Any]:
        working = image.convert("RGB")
        last_quality = quality
        for current_quality in range(quality, minimum_quality - 1, -quality_step):
            last_quality = current_quality
            working.save(
                destination,
                format=output_format,
                quality=current_quality,
                optimize=True,
            )
            if destination.stat().st_size <= target_bytes:
                return {
                    "quality": current_quality,
                    "target_bytes": target_bytes,
                    "target_reached": True,
                    "warnings": [],
                }
        return {
            "quality": last_quality,
            "target_bytes": target_bytes,
            "target_reached": False,
            "warnings": [
                "Image exceeded workbook target size at the minimum allowed quality; "
                "kept the smallest safe output instead."
            ],
        }
