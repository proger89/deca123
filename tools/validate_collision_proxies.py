"""Validate locked collision-proxy realism SLOs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast


def _number(value: object) -> float:
    if not isinstance(value, int | float):
        raise RuntimeError("proxy metric must be numeric")
    return float(value)


def validate(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = cast(list[dict[str, object]], manifest["items"])
    failures: list[str] = []
    for row in rows:
        family = str(row["family"])
        bbox_limit = max(3.0, max(_number(value) for value in cast(list[object], row["bbox_mm"])) * 0.02)
        checks = (
            _number(row["bbox_error_mm"]) <= bbox_limit,
            0.90 <= _number(row["volume_ratio"]) <= 1.10,
            _number(row["footprint_iou"]) >= 0.90,
            _number(row["center_of_mass_error_mm"]) <= 5.0,
            _number(row["inertia_error_percent"]) <= 10.0,
        )
        if not all(checks):
            failures.append(family)
    return {
        "failures": failures,
        "items": len(rows),
        "max_bbox_error_mm": max(_number(row["bbox_error_mm"]) for row in rows),
        "min_footprint_iou": min(_number(row["footprint_iou"]) for row in rows),
        "result": "pass" if not failures else "fail",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate(args.manifest)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
