from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessedVideo:
    video: Path
    poster: Path
    operations: tuple[str, ...]


class FfmpegVideoProcessor:
    """Create a web-ready MP4 and poster without retaining the source upload."""

    def process(self, source: Path, destination_dir: Path, stem: str) -> ProcessedVideo:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("Video processing requires ffmpeg.")
        destination_dir.mkdir(parents=True, exist_ok=True)
        video = destination_dir / f"{stem}.mp4"
        poster = destination_dir / f"{stem}-poster.jpg"
        # ffmpeg's default (all CPU cores, preset medium) peaked at ~810 MB on a 20 s 1080p clip and
        # crashed the 512 MB Render instance. One thread + veryfast peaks at ~280 MB, only a bit slower.
        # Raise V2_FFMPEG_THREADS when the Render plan gets more memory (see docs/agent_handoff.md).
        threads = os.getenv("V2_FFMPEG_THREADS", "1")
        scale = "scale='min(1920,iw)':-2:force_original_aspect_ratio=decrease"
        self._run([
            ffmpeg, "-y", "-threads", threads, "-i", str(source), "-map_metadata", "-1",
            "-vf", scale, "-filter_threads", threads,
            "-c:v", "libx264", "-preset", "veryfast", "-threads", threads, "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(video),
        ])
        self._run([
            ffmpeg, "-y", "-ss", "0.5", "-i", str(video), "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2:force_original_aspect_ratio=decrease",
            "-q:v", "3", str(poster),
        ])
        if not video.is_file() or not poster.is_file():
            raise RuntimeError("ffmpeg did not create the processed video and poster.")
        return ProcessedVideo(
            video=video,
            poster=poster,
            operations=("h264_crf_23", "max_1080p", "aac_128k", "faststart", "poster_0.5s"),
        )

    @staticmethod
    def _run(command: list[str]) -> None:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
            raise RuntimeError(detail[-1200:])
