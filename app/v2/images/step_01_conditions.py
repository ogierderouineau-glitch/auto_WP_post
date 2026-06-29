from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageConditionContext:
    width: int
    height: int
    filesize_bytes: int
    values: dict[str, Any]
    analysis: dict[str, Any]


ImageCondition = Callable[[ImageConditionContext, Any], bool]

IMAGE_CONDITION_HANDLERS: dict[str, ImageCondition] = {
    "always": lambda _ctx, _value: True,
    "width_gt_value": lambda ctx, value: ctx.width > int(value),
    "height_gt_value": lambda ctx, value: ctx.height > int(value),
    "filesize_gt_target": lambda ctx, _value: (
        ctx.filesize_bytes > int(ctx.values.get("compression.target_kb", 0)) * 1024
    ),
    "crop_mode_equals_cover": lambda ctx, _value: ctx.values.get("crop.mode") == "cover",
    "image_dark": lambda ctx, _value: float(ctx.analysis.get("brightness_score", 100)) < 45,
    "noise_score_gt_20": lambda ctx, _value: float(ctx.analysis.get("noise_score", 0)) > 20,
    "subject_mask_available": lambda ctx, _value: bool(ctx.analysis.get("subject_mask")),
}


def image_condition_matches(name: str, context: ImageConditionContext, value: Any) -> bool:
    try:
        return IMAGE_CONDITION_HANDLERS[name](context, value)
    except KeyError as exc:
        raise ValueError(f"Unknown image-processing condition: {name}") from exc
