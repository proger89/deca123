"""Run the clean isolation audit and an in-memory planted leak canary."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.check_architecture import (  # noqa: E402
    ArchitectureError,
    scan_runtime_files,
    verify_architecture,
)


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-canary", action="store_true", required=True)
    parser.parse_args(argv)

    try:
        clean_before = verify_architecture()
    except ArchitectureError as error:
        emit({"clean_pass": False, "error": str(error), "result": "fail"})
        return 1

    with TemporaryDirectory(prefix="safesort-leak-canary-") as directory:
        canary = Path(directory) / "runtime_canary.py"
        canary.write_text(
            "from controller import Supervisor\nreverse = Receiver('evaluator_to_runtime')\n",
            encoding="utf-8",
        )
        findings = scan_runtime_files([canary])

    try:
        clean_after = verify_architecture()
    except ArchitectureError as error:
        emit({"clean_pass": False, "error": str(error), "result": "fail"})
        return 1
    canary_rejected = len(findings) >= 2
    result = "pass" if canary_rejected else "fail"
    emit(
        {
            "canary_findings": findings,
            "canary_rejected": canary_rejected,
            "clean_findings_after": clean_after["forbidden_findings"],
            "clean_findings_before": clean_before["forbidden_findings"],
            "result": result,
        }
    )
    return 0 if canary_rejected else 1


if __name__ == "__main__":
    raise SystemExit(main())
