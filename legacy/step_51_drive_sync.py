import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def run_rclone(
    command: list[str],
    root_folder_id: str | None = None,
) -> subprocess.CompletedProcess[str]:
    full_command = ["rclone"]
    if root_folder_id:
        full_command.extend(["--drive-root-folder-id", root_folder_id])
    full_command.extend(command)
    response = subprocess.run(
        full_command,
        check=False,
        text=True,
        capture_output=True,
    )
    if response.returncode != 0:
        raise RuntimeError(
            "rclone failed:\n"
            + " ".join(full_command)
            + "\nSTDOUT:\n"
            + response.stdout
            + "\nSTDERR:\n"
            + response.stderr
        )
    return response


def remote_child(remote_root: str, child_name: str) -> str:
    return f"{remote_root.rstrip('/')}/{child_name}"


def is_bare_rclone_remote(remote: str) -> bool:
    return remote.endswith(":") and "/" not in remote


def ensure_rclone_available() -> None:
    if not shutil.which("rclone"):
        raise FileNotFoundError("rclone is not installed or not available on PATH.")


def rclone_remote_items(
    rclone_source: str,
    processed_dir_name: str,
    root_folder_id: str | None = None,
) -> list[dict[str, Any]]:
    ensure_rclone_available()
    response = run_rclone(["lsjson", rclone_source, "--max-depth", "1"], root_folder_id)
    items = json.loads(response.stdout or "[]")
    candidates: list[dict[str, Any]] = []
    for item in items:
        name = item.get("Name", "")
        if not name or name.startswith(".") or name == processed_dir_name:
            continue
        if item.get("IsDir"):
            candidates.append({"name": name, "is_dir": True})
        elif name.lower().endswith(".zip"):
            candidates.append({"name": name, "is_dir": False})
    return candidates


def download_rclone_item(
    rclone_source: str,
    item: dict[str, Any],
    batch_root: Path,
    root_folder_id: str | None = None,
) -> Path:
    batch_root.mkdir(parents=True, exist_ok=True)
    remote_item = remote_child(rclone_source, item["name"])
    local_item = batch_root / item["name"]

    if local_item.exists():
        print(f"Local item already exists, using it: {local_item}")
        return local_item

    if item["is_dir"]:
        run_rclone(["copy", remote_item, str(local_item)], root_folder_id)
    else:
        run_rclone(["copyto", remote_item, str(local_item)], root_folder_id)

    print(f"Downloaded Drive item: {remote_item} -> {local_item}")
    return local_item


def move_rclone_item_to_processed(
    rclone_source: str,
    input_path: Path,
    processed_dir_name: str,
    root_folder_id: str | None = None,
) -> str:
    source_remote = remote_child(rclone_source, input_path.name)
    processed_remote_dir = remote_child(rclone_source, processed_dir_name)
    destination_remote = remote_child(processed_remote_dir, input_path.name)
    run_rclone(["mkdir", processed_remote_dir], root_folder_id)
    run_rclone(["moveto", source_remote, destination_remote], root_folder_id)
    return destination_remote
