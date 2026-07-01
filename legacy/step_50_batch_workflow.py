import argparse
from pathlib import Path
from typing import Callable

from legacy.step_10_event_payload import safe_name, write_json
from legacy.step_51_drive_sync import (
    download_rclone_item,
    is_bare_rclone_remote,
    move_rclone_item_to_processed,
    rclone_remote_items,
    remote_child,
)
from legacy.step_52_processed_files import (
    find_companion_zip,
    is_batch_candidate,
    move_to_processed,
    sync_from_source,
)


RunImport = Callable[[argparse.Namespace], Path]


def clone_args_for_batch_item(args: argparse.Namespace, input_path: Path) -> argparse.Namespace:
    item_args = argparse.Namespace(**vars(args))
    item_args.event_name = args.event_name or safe_name(input_path.stem if input_path.is_file() else input_path.name)

    if input_path.is_file():
        item_args.zip_path = input_path
        item_args.event_dir = None
    else:
        item_args.event_dir = input_path
        item_args.zip_path = None

    return item_args


def run_batch_import(args: argparse.Namespace, run_import: RunImport) -> None:
    # 1. Optionally pull only direct event folders/zip files from a local mirror or Drive.
    batch_root = args.batch_root
    if not batch_root.exists() or not batch_root.is_dir():
        raise NotADirectoryError(f"Batch root is not a directory: {batch_root}")

    synced: list[dict[str, str]] = []
    rclone_synced: list[dict[str, str]] = []
    if args.sync_source:
        synced = sync_from_source(args.sync_source, batch_root, args.processed_dir_name)
    if args.rclone_source:
        if (
            is_bare_rclone_remote(args.rclone_source)
            and not args.rclone_root_folder_id
            and not args.allow_rclone_root
        ):
            raise ValueError(
                "Refusing to scan a bare Drive remote root. Use a specific folder path, "
                "for example flairlabdrive:event-posts, pass --rclone-root-folder-id, "
                "or pass --allow-rclone-root."
            )
        remote_items = rclone_remote_items(
            args.rclone_source,
            args.processed_dir_name,
            args.rclone_root_folder_id,
        )
        for remote_item in remote_items:
            downloaded = download_rclone_item(
                args.rclone_source,
                remote_item,
                batch_root,
                args.rclone_root_folder_id,
            )
            rclone_synced.append({
                "source": remote_child(args.rclone_source, remote_item["name"]),
                "destination": str(downloaded),
            })

    # 2. Process every direct candidate in the batch folder.
    candidates = sorted(
        path for path in batch_root.iterdir()
        if is_batch_candidate(path, args)
    )

    if not candidates:
        print(f"No event folders or zip files to process in: {batch_root}")
        write_batch_summary(args, synced, rclone_synced, [], [])
        return

    print(f"Found {len(candidates)} batch item(s) in {batch_root}")
    successes: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    for input_path in candidates:
        if not input_path.exists():
            print(f"\nSkipping already moved batch item: {input_path}")
            continue

        print(f"\nProcessing batch item: {input_path}")
        item_args = clone_args_for_batch_item(args, input_path)
        try:
            output_dir = run_import(item_args)
        except Exception as exc:
            failures.append({"input": str(input_path), "error": str(exc)})
            print(f"Batch item failed: {input_path}")
            print(exc)
            continue

        # 3. After a successful import, move local and remote inputs to processed.
        moved_to = ""
        companion_zip_moved_to = ""
        rclone_moved_to = ""
        if args.live or args.move_after_dry_run:
            companion_zip = find_companion_zip(input_path)
            moved_to_path = move_to_processed(input_path, batch_root, args.processed_dir_name)
            moved_to = str(moved_to_path)
            print(f"Moved processed input to: {moved_to_path}")
            if args.rclone_source:
                rclone_moved_to = move_rclone_item_to_processed(
                    args.rclone_source,
                    input_path,
                    args.processed_dir_name,
                    args.rclone_root_folder_id,
                )
                print(f"Moved Drive item to: {rclone_moved_to}")
            if companion_zip:
                companion_destination = move_to_processed(companion_zip, batch_root, args.processed_dir_name)
                companion_zip_moved_to = str(companion_destination)
                print(f"Moved companion zip to: {companion_destination}")
                if args.rclone_source:
                    companion_rclone_moved_to = move_rclone_item_to_processed(
                        args.rclone_source,
                        companion_zip,
                        args.processed_dir_name,
                        args.rclone_root_folder_id,
                    )
                    print(f"Moved Drive companion zip to: {companion_rclone_moved_to}")
        else:
            print("Dry run complete; input left in place. Use --move-after-dry-run to move dry-run inputs.")

        successes.append({
            "input": str(input_path),
            "output_dir": str(output_dir),
            "moved_to": moved_to,
            "companion_zip_moved_to": companion_zip_moved_to,
            "rclone_moved_to": rclone_moved_to,
        })

    write_batch_summary(args, synced, rclone_synced, successes, failures)
    print(
        f"\nBatch complete: {len(successes)} succeeded, {len(failures)} failed. "
        f"Summary: {args.output_root / 'batch_last_run.json'}"
    )


def write_batch_summary(
    args: argparse.Namespace,
    synced: list[dict[str, str]],
    rclone_synced: list[dict[str, str]],
    successes: list[dict[str, str]],
    failures: list[dict[str, str]],
) -> None:
    summary = {
        "batch_root": str(args.batch_root),
        "processed_dir": str(args.batch_root / args.processed_dir_name),
        "synced": synced,
        "rclone_synced": rclone_synced,
        "successes": successes,
        "failures": failures,
    }
    write_json(args.output_root / "batch_last_run.json", summary)
