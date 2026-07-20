"""Reject unsupported 7200/h marketing claims."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def verify(bundle: Path) -> dict[str, object]:
    claim = json.loads((bundle / "claim-status.json").read_text(encoding="utf-8"))
    report = json.loads((bundle / "throughput-report.json").read_text(encoding="utf-8"))
    proxy_invariants = int(report["unsafe_to_b"]) == int(report["jams"]) == int(report["lost"]) == 0
    honest = (
        claim["result"] == "UNSUPPORTED"
        and "5143" in claim["supported_profile"]
        and report.get("physical_safety_claim") is False
        and "proxy" in str(report.get("evidence_scope", ""))
    )
    return {
        "claim_7200": claim["result"],
        "honest_status": honest,
        "proxy_safety_invariants": proxy_invariants,
        "result": "pass" if honest and proxy_invariants else "fail",
        "supported_profile": claim["supported_profile"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify(args.bundle)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
