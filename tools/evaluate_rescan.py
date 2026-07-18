"""Verify safe rescan economics, interval coverage and bottom-view decision."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]


def evaluate(bundle: Path) -> dict[str, object]:
    payload = json.loads((bundle / "uncertainty-summary.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("uncertainty summary must be an object")
    data = cast(dict[str, Any], payload)
    rescan = cast(dict[str, Any], data["rescan"])
    bottom = cast(dict[str, Any], data["bottom_view"])
    risk = cast(dict[str, Any], data["risk_coverage"])
    checks = {
        "bands_locked": float(cast(dict[str, Any], data["bands"])["dimension_half_width_mm"]) >= 5.0
        and float(cast(dict[str, Any], data["bands"])["circularity_half_width_k"]) >= 0.03,
        "bottom_rule_applied": bottom["decision"] == "DISABLE" and bottom["enabled_in_release"] is False,
        "coverage_calibrated": float(data["interval_coverage"]) >= 0.95,
        "mutation_rejected": data["post_result_mutation_rejected"] is True,
        "rescan_safe": int(rescan["unsafe_to_b_after"]) <= int(rescan["unsafe_to_b_before"]),
        "rescan_cost_reported": 0.0 <= float(rescan["throughput_cost_percent"]) <= 10.0,
        "risk_includes_abstains": risk["abstains_in_denominator"] is True,
        "risk_has_ci": float(risk["risk_ci_high"]) >= float(risk["risk_ci_low"]),
    }
    if not all(checks.values()):
        raise RuntimeError("rescan evaluation failed: " + ", ".join(name for name, value in checks.items() if not value))
    return {"bottom_view": bottom, "checks": checks, "rescan": rescan, "result": "pass", "risk_coverage": risk}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    bundle = Path(str(args.bundle))
    if not bundle.is_absolute():
        bundle = ROOT / bundle
    try:
        result = evaluate(bundle)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        result = {"error": str(error), "result": "fail"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
