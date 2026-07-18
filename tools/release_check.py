"""Re-run the frozen release suite from independent clean Git clones."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_release_check(repeat: int, *, clean_clone: bool) -> dict[str, object]:
    if repeat < 1:
        raise RuntimeError("repeat must be positive")
    if not clean_clone:
        raise RuntimeError("phase-15 release check requires --clean-clone")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()
    output = ROOT / "artifacts" / "phase-15" / "clean-clones"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    runs: list[dict[str, object]] = []
    for index in range(1, repeat + 1):
        clone = output / f"clone-{index}"
        clone_result = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(clone)], cwd=ROOT, check=False
        )
        if clone_result.returncode != 0:
            runs.append({"clone": index, "exit_code": clone_result.returncode, "result": "fail"})
            break
        checked_revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, check=True, text=True
        ).stdout.strip()
        run_result = subprocess.run(
            [
                sys.executable,
                "run_scenario.py",
                "suite",
                "--profile",
                "release",
                "--repeat",
                "3",
                "--record-video",
                "--output",
                "artifacts/release-check",
            ],
            cwd=clone,
            check=False,
        )
        summary_path = clone / "artifacts" / "release-check" / "release-summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
        passed = run_result.returncode == 0 and checked_revision == revision and summary.get("result") == "pass"
        runs.append(
            {
                "clone": index,
                "exit_code": run_result.returncode,
                "revision": checked_revision,
                "semantic_hashes": summary.get("semantic_hashes", []),
                "result": "pass" if passed else "fail",
            }
        )
        shutil.rmtree(clone)
        if not passed:
            break
    passed = len(runs) == repeat and all(run["result"] == "pass" for run in runs)
    summary = {"clean_clones": runs, "repeat": repeat, "revision": revision, "result": "pass" if passed else "fail"}
    summary_path = ROOT / "artifacts" / "phase-15" / "clean-clone-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
