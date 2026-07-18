"""Compare analytical capacity/cycle and measured flow evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def compare(bundle: Path) -> dict[str, object]:
    report = json.loads((bundle / "throughput-report.json").read_text(encoding="utf-8"))
    checks = {
        "actuation_delta_under_10": float(report["actuation_delta_percent"]) < 10.0,
        "arrivals_5143": int(report["arrivals"]) == 5143,
        "cycle_delta_under_5": float(report["cycle_delta_percent"]) <= 5.0,
        "exits_match": int(report["exits"]) == int(report["arrivals"]),
        "stopping_delta_under_10": float(report["stopping_delta_percent"]) < 10.0,
    }
    return {"checks": checks, "result": "pass" if all(checks.values()) else "fail"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(args.bundle)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
