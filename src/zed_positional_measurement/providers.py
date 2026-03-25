from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .models import CornerDetection, PaperDetection
from .storage import read_jsonl


@dataclass
class SegmentJsonlPaperProvider:
    root_dir: Path | None

    def get(self, segment_id: str, frame_idx: int) -> list[PaperDetection]:
        if self.root_dir is None:
            return []
        path = Path(self.root_dir) / f"{segment_id}.jsonl"
        by_frame: dict[int, list[PaperDetection]] = defaultdict(list)
        for row in read_jsonl(path):
            detection = PaperDetection.from_dict(row)
            by_frame[detection.frame_idx].append(detection)
        return by_frame.get(frame_idx, [])


@dataclass
class TailingPaperProvider:
    """Reads detection JSONL written by Worker 1 (NN detector), waiting for new lines as needed.

    Worker 1 writes one JSONL line per frame as it processes SVO2 segments.
    This provider tails that file, polling for new lines when Worker 2 is ahead
    of Worker 1, with a configurable timeout.
    """

    root_dir: Path | None
    poll_interval_ms: int = 100
    timeout_ms: int = 30000
    _cache: dict[str, dict[int, list[PaperDetection]]] = field(default_factory=dict, repr=False)
    _file_offsets: dict[str, int] = field(default_factory=dict, repr=False)

    def get(self, segment_id: str, frame_idx: int) -> list[PaperDetection]:
        if self.root_dir is None:
            return []
        cache_key = segment_id
        if cache_key not in self._cache:
            self._cache[cache_key] = defaultdict(list)
            self._file_offsets[cache_key] = 0

        by_frame = self._cache[cache_key]
        if frame_idx in by_frame:
            return by_frame[frame_idx]

        # Poll for new lines until we find data for frame_idx or timeout
        path = Path(self.root_dir) / f"{segment_id}.jsonl"
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while time.monotonic() < deadline:
            new_lines = self._read_new_lines(path, cache_key)
            for row in new_lines:
                detection = PaperDetection.from_dict(row)
                by_frame[detection.frame_idx].append(detection)
            if frame_idx in by_frame:
                return by_frame[frame_idx]
            if not new_lines:
                time.sleep(self.poll_interval_ms / 1000.0)

        # Timeout — return empty (frame emitted without paper detections)
        return []

    def _read_new_lines(self, path: Path, cache_key: str) -> list[dict]:
        if not path.exists():
            return []
        rows: list[dict] = []
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(self._file_offsets[cache_key])
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
            self._file_offsets[cache_key] = handle.tell()
        return rows


@dataclass
class SegmentJsonlCornerProvider:
    root_dir: Path | None

    def get(self, segment_id: str, frame_idx: int) -> list[CornerDetection]:
        if self.root_dir is None:
            return []
        path = Path(self.root_dir) / f"{segment_id}.jsonl"
        by_frame: dict[int, list[CornerDetection]] = defaultdict(list)
        for row in read_jsonl(path):
            detection = CornerDetection.from_dict(row)
            by_frame[detection.frame_idx].append(detection)
        return by_frame.get(frame_idx, [])
