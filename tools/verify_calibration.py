"""Validate the immutable five-view calibration and its detached SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
PRIMARY_VIEWS = ("top", "left", "right", "front", "rear")


class CalibrationError(RuntimeError):
    """Raised when calibration structure or provenance is invalid."""


def calibration_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_calibration(path: Path, *, expected_hash: str | None = None) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CalibrationError("calibration must be an object")
    data = cast(dict[str, Any], payload)
    views = cast(dict[str, Any], data.get("views", {}))
    if tuple(views) != PRIMARY_VIEWS:
        raise CalibrationError("primary views must be top,left,right,front,rear in locked order")
    if data.get("sampling_period_ms") != 32:
        raise CalibrationError("sampling period must equal one 32 ms simulation step")
    axes = cast(dict[str, str], data.get("axes", {}))
    if axes.get("world") != "NUE_y_up" or axes.get("sensor_forward") != "+X":
        raise CalibrationError("axis convention mismatch")
    bottom = cast(dict[str, object], cast(dict[str, Any], data.get("experimental_views", {})).get("bottom", {}))
    if bottom.get("enabled") is not False or bottom.get("release_authority") is not False:
        raise CalibrationError("bottom experiment must be disabled and non-authoritative")
    digest = calibration_hash(path)
    detached = path.with_suffix(".sha256")
    if not detached.is_file() or detached.read_text(encoding="ascii").strip() != digest:
        raise CalibrationError("detached calibration hash mismatch")
    if expected_hash is not None and digest != expected_hash:
        raise CalibrationError("runtime expected calibration hash mismatch")
    return {"calibration_hash": digest, "result": "pass", "sampling_period_ms": 32, "view_count": len(views)}


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-hash")
    args = parser.parse_args(argv)
    path = Path(str(args.config))
    if not path.is_absolute():
        path = ROOT / path
    try:
        summary = validate_calibration(path, expected_hash=str(args.expected_hash) if args.expected_hash else None)
    except CalibrationError as error:
        emit({"error": str(error), "result": "fail"})
        return 1
    emit(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
