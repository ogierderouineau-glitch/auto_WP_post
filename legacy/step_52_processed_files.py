import argparse
import shutil
from pathlib import Path


def is_batch_candidate(path: Path, args: argparse.Namespace) -> bool:
    if path.name.startswith("."):
        return False
    if path.name == args.processed_dir_name:
        return False

    try:
        if path.resolve() == args.output_root.resolve():
            return False
    except FileNotFoundError:
        pass

    if path.is_file():
        return path.suffix.lower() == ".zip"

    if path.is_dir():
        return True

    return False


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 2
    while True:
        if path.suffix:
            candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        else:
            candidate = path.with_name(f"{path.name}-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def move_to_processed(input_path: Path, batch_root: Path, processed_dir_name: str) -> Path:
    processed_dir = batch_root / processed_dir_name
    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(processed_dir / input_path.name)
    shutil.move(str(input_path), str(destination))
    return destination


def find_companion_zip(input_path: Path) -> Path | None:
    if not input_path.is_dir():
        return None

    candidate = input_path.with_suffix(".zip")
    if candidate.exists() and candidate.is_file():
        return candidate

    return None


def is_sync_candidate(path: Path, processed_dir_name: str) -> bool:
    if path.name.startswith("."):
        return False
    if path.name == processed_dir_name:
        return False
    if path.is_file():
        return path.suffix.lower() == ".zip"
    return path.is_dir()


def sync_from_source(sync_source: Path, batch_root: Path, processed_dir_name: str) -> list[dict[str, str]]:
    if not sync_source.exists() or not sync_source.is_dir():
        raise NotADirectoryError(f"Sync source is not a directory: {sync_source}")

    batch_root.mkdir(parents=True, exist_ok=True)
    synced: list[dict[str, str]] = []

    for source_path in sorted(sync_source.iterdir()):
        if not is_sync_candidate(source_path, processed_dir_name):
            continue

        destination = batch_root / source_path.name
        processed_destination = batch_root / processed_dir_name / source_path.name

        if destination.exists() or processed_destination.exists():
            print(f"Already synced or processed, skipping: {source_path.name}")
            continue

        if source_path.is_dir():
            shutil.copytree(source_path, destination)
        else:
            shutil.copy2(source_path, destination)

        synced.append({"source": str(source_path), "destination": str(destination)})
        print(f"Synced from cloud mirror: {source_path} -> {destination}")

    return synced
