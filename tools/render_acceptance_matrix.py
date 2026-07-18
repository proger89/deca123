"""Render and verify the deterministic judge-facing acceptance matrix."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from safesort.contracts.acceptance import (  # noqa: E402
    CONTRACT_PATH,
    LOCK_PATH,
    MATRIX_PATH,
    expected_lock,
    load_object,
    render_matrix,
)


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def encoded_json(data: dict[str, object]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_outputs() -> int:
    contract = load_object(CONTRACT_PATH)
    matrix = render_matrix(contract)
    MATRIX_PATH.write_bytes(matrix.encode("utf-8"))
    lock = expected_lock(matrix)
    LOCK_PATH.write_bytes(encoded_json(lock))
    emit(
        {
            "action": "write",
            "lock": str(LOCK_PATH.relative_to(ROOT)),
            "matrix": str(MATRIX_PATH.relative_to(ROOT)),
            "result": "pass",
        }
    )
    return 0


def check_outputs() -> int:
    contract = load_object(CONTRACT_PATH)
    expected_matrix = render_matrix(contract)
    if not MATRIX_PATH.is_file() or MATRIX_PATH.read_text(encoding="utf-8") != expected_matrix:
        emit({"error": "rendered acceptance matrix is stale", "result": "fail"})
        return 1
    expected = expected_lock(expected_matrix)
    if not LOCK_PATH.is_file() or load_object(LOCK_PATH) != expected:
        emit({"error": "contract lock is stale", "result": "fail"})
        return 1
    emit({"action": "check", "matrix_sha256": expected["rendered_matrix_sha256"], "result": "pass"})
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    return write_outputs() if args.write else check_outputs()


if __name__ == "__main__":
    raise SystemExit(main())
