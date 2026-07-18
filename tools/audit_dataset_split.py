"""Verify frozen calibration/hidden split disjointness and hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def _hash_values(values: list[object]) -> str:
    encoded = json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def audit(bundle: Path) -> dict[str, object]:
    payload = json.loads((bundle / "dataset-split.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("split manifest must be an object")
    data = cast(dict[str, Any], payload)
    calibration = cast(dict[str, Any], data["calibration"])
    hidden = cast(dict[str, Any], data["hidden"])
    checks = {
        "families_disjoint": set(calibration["families"]).isdisjoint(hidden["families"]),
        "frozen": data["frozen_before_evaluation"] is True,
        "ids_disjoint": set(calibration["ids"]).isdisjoint(hidden["ids"]),
        "seeds_disjoint": set(calibration["seeds"]).isdisjoint(hidden["seeds"]),
        "calibration_hash_valid": calibration["split_hash"]
        == _hash_values([calibration["ids"], calibration["seeds"], calibration["families"]]),
        "hidden_hash_valid": hidden["split_hash"] == _hash_values([hidden["ids"], hidden["seeds"], hidden["families"]]),
    }
    if not all(checks.values()):
        raise RuntimeError("dataset split audit failed")
    return {"checks": checks, "result": "pass", "split_hashes": [calibration["split_hash"], hidden["split_hash"]]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    bundle = Path(str(args.bundle))
    if not bundle.is_absolute():
        bundle = ROOT / bundle
    try:
        result = audit(bundle)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        result = {"error": str(error), "result": "fail"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
