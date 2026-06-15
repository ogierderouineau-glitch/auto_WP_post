import shutil
from pathlib import Path
from typing import Any

from step_10_event_payload import find_picture_files
from step_21_compress_photo import compress_image_to_target


COMPRESSIBLE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def prepare_event_images(
    event_dir: Path,
    output_dir: Path,
    compress_images: bool,
    target_kb: int,
    min_quality: int,
    start_quality: int,
    min_width: int,
) -> tuple[Path, dict[str, Any]]:
    if not compress_images:
        return event_dir, {
            "enabled": False,
            "event_dir": str(event_dir),
        }

    compressed_event_dir = output_dir / "compressed_event"
    if compressed_event_dir.exists():
        shutil.rmtree(compressed_event_dir)
    compressed_event_dir.mkdir(parents=True, exist_ok=True)

    log: dict[str, Any] = {
        "enabled": True,
        "source_event_dir": str(event_dir),
        "compressed_event_dir": str(compressed_event_dir),
        "target_kb": target_kb,
        "min_quality": min_quality,
        "start_quality": start_quality,
        "min_width": min_width,
        "items": [],
    }

    for source_path in find_picture_files(event_dir):
        relative_path = source_path.relative_to(event_dir)
        destination_path = compressed_event_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if source_path.suffix.lower() not in COMPRESSIBLE_IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image type for compression: {source_path}")

        if source_path.suffix.lower() not in {".jpg", ".jpeg"}:
            destination_path = destination_path.with_suffix(".jpg")
        compress_image_to_target(
            input_path=source_path,
            output_path=destination_path,
            target_kb=target_kb,
            min_quality=min_quality,
            start_quality=start_quality,
            min_width=min_width,
        )
        status = "compressed"

        log["items"].append({
            "source": str(source_path),
            "destination": str(destination_path),
            "status": status,
            "source_size_kb": round(source_path.stat().st_size / 1024, 1),
            "destination_size_kb": round(destination_path.stat().st_size / 1024, 1),
        })

    return compressed_event_dir, log
