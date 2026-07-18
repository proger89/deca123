"""Verify analytical-versus-simulated mechanics evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def compare(bundle: Path) -> dict[str, object]:
    payload = json.loads((bundle / "mechanics.json").read_text(encoding="utf-8"))
    deltas = {
        "actuation_percent": float(payload["actuation_calculation_delta_percent"]),
        "return_percent": float(payload["return_time_delta_percent"]),
        "stopping_percent": float(payload["stopping_calculation_delta_percent"]),
    }
    passed = all(value < 10.0 for value in deltas.values())
    return {"deltas": deltas, "result": "pass" if passed else "fail"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(args.bundle)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
