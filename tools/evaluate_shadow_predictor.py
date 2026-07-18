"""Verify shadow predictor gain, split isolation and lack of gate authority."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def evaluate(bundle: Path) -> dict[str, object]:
    predictor = json.loads((bundle / "shadow-predictor.json").read_text(encoding="utf-8"))
    paired = json.loads((bundle / "paired-results.json").read_text(encoding="utf-8"))
    checks = {
        "authority_canary_rejected": predictor["authority_canary"] == "REJECTED" and predictor["actuation_authority"] is False,
        "brier_improved": float(predictor["brier_predictor"]) < float(predictor["brier_constant_baseline"]),
        "four_paired_experiments": len(paired["experiments"]) == 4,
        "mesh_disjoint": int(predictor["mesh_overlap"]) == 0,
        "seed_disjoint": int(predictor["seed_overlap"]) == 0,
        "shadow_only": predictor["recommendation_channel"] == "shadow_log_only",
    }
    status = "IMPROVED" if checks["brier_improved"] else "NO_GAIN"
    return {"checks": checks, "result": "pass" if all(checks.values()) else "fail", "status": status}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate(args.bundle)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
