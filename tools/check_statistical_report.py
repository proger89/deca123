"""Check locked reliability statistics and confidence reporting."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def check(bundle: Path) -> dict[str, object]:
    report = json.loads((bundle / "statistical-report.json").read_text(encoding="utf-8"))
    checks = {
        "abstains_honest": report["abstains_in_accuracy_denominator"] is True,
        "accuracy_target": float(report["official_accuracy"]) >= 0.99,
        "blind_macro_f1": float(report["blind"]["macro_f1"]) >= 0.98,
        "coverage_target": float(report["automation_coverage"]) >= 0.97,
        "dimension_p95": float(report["dimension_error_p95_mm"]) <= 5.0,
        "five_seeds": len(report["seeds"]) == 5,
        "k_p95": float(report["k_error_p95"]) <= 0.05,
        "risk_ci_present": len(report["risk_95_ci"]) == 2,
        "rule_of_three_present": float(report["rule_of_three_upper_95"]) > 0.0,
        "unsafe_b_zero": int(report["unsafe_to_b"]) == 0,
    }
    return {"checks": checks, "result": "pass" if all(checks.values()) else "fail"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    result = check(args.bundle)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
