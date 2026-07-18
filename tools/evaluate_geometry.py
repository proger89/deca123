"""Verify retained geometry errors, methods, invalid semantics and isolation evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain an object")
    return cast(dict[str, Any], payload)


def evaluate(bundle: Path) -> dict[str, object]:
    summary = load_object(bundle / "geometry-summary.json")
    dimension = cast(dict[str, float], summary["dimension_error_mm"])
    k_error = cast(dict[str, float], summary["k_error"])
    invalid = cast(dict[str, str], summary["invalid_cases"])
    lookup = cast(dict[str, object], summary["lookup_denial"])
    checks = {
        "boundary_outcomes_unchanged": summary["boundary_final_outcome_changes"] == 0,
        "dimension_p95_le_5mm": float(dimension["p95"]) <= 5.0,
        "invalid_cases_typed": invalid
        == {
            "coverage": "UNRESOLVED_COVERAGE",
            "excess_gap": "UNRESOLVED_EXCESS_GAP",
            "open_contour": "UNRESOLVED_OPEN_CONTOUR",
        },
        "k_p95_le_0_05": float(k_error["p95"]) <= 0.05,
        "lookup_denied": lookup.get("passed") is True,
        "overlays_present": (bundle / "obb-overlay.svg").is_file() and (bundle / "slice-overlay.svg").is_file(),
        "refinement_exercised": int(summary["refined_count"]) > 0,
        "rename_invariant": summary["rename_invariant"] is True,
        "rows_present": (bundle / "geometry-errors.csv").is_file() and int(summary["case_count"]) >= 50,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError("geometry evaluation failed: " + ", ".join(failed))
    return {
        "case_count": summary["case_count"],
        "checks": checks,
        "dimension_error_mm": dimension,
        "k_error": k_error,
        "result": "pass",
        "stage_timing_median_ms": summary["stage_timing_median_ms"],
    }


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    bundle = Path(str(args.bundle))
    if not bundle.is_absolute():
        bundle = ROOT / bundle
    try:
        summary = evaluate(bundle)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        emit({"error": str(error), "result": "fail"})
        return 1
    emit(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
