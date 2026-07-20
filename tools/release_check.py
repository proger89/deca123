"""Re-run the frozen release suite from independent clean Git clones."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_release_check(repeat: int, *, clean_clone: bool) -> dict[str, object]:
    if repeat < 1:
        raise RuntimeError("repeat must be positive")
    if not clean_clone:
        raise RuntimeError("phase-15 release check requires --clean-clone")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()
    root_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    root_clean = not root_status
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
            if clone.exists():
                shutil.rmtree(clone)
            break
        try:
            checked_revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, check=True, text=True
            ).stdout.strip()
            clone_status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=clone,
                capture_output=True,
                check=True,
                text=True,
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
            manifest_path = clone / "artifacts" / "release-check" / "release-manifest.json"
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
                manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                summary = {}
                manifest = {}
            semantic_hashes = summary.get("semantic_hashes", [])
            semantic_identical = (
                isinstance(semantic_hashes, list)
                and len(semantic_hashes) == 3
                and len(set(semantic_hashes)) == 1
                and semantic_hashes == manifest.get("semantic_hashes")
            )
            manifest_bound_to_clone = (
                manifest.get("commit") == checked_revision
                and manifest.get("dirty") is False
                and manifest.get("network") == "none"
                and manifest.get("repeat") == 3
            )
            passed = (
                run_result.returncode == 0
                and checked_revision == revision
                and not clone_status
                and summary.get("result") == "pass"
                and semantic_identical
                and manifest_bound_to_clone
            )
            runs.append(
                {
                    "clone": index,
                    "clone_clean_before_run": not clone_status,
                    "exit_code": run_result.returncode,
                    "manifest_bound_to_clone": manifest_bound_to_clone,
                    "manifest_sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
                    "revision": checked_revision,
                    "semantic_hashes": semantic_hashes,
                    "source_event_hash": manifest.get("source_event_hash"),
                    "result": "pass" if passed else "fail",
                }
            )
        finally:
            if clone.exists():
                shutil.rmtree(clone)
        if not passed:
            break
    clone_semantic_hashes = [run["semantic_hashes"] for run in runs]
    cross_clone_semantic_identical = len(clone_semantic_hashes) == repeat and all(
        hashes == clone_semantic_hashes[0] for hashes in clone_semantic_hashes
    )
    source_event_hashes = [run["source_event_hash"] for run in runs]
    cross_clone_event_identical = len(source_event_hashes) == repeat and all(
        digest and digest == source_event_hashes[0] for digest in source_event_hashes
    )
    passed = (
        root_clean
        and len(runs) == repeat
        and all(run["result"] == "pass" for run in runs)
        and cross_clone_semantic_identical
        and cross_clone_event_identical
    )
    summary = {
        "clean_clones": runs,
        "cross_clone_event_identical": cross_clone_event_identical,
        "cross_clone_semantic_identical": cross_clone_semantic_identical,
        "repeat": repeat,
        "revision": revision,
        "root_clean": root_clean,
        "result": "pass" if passed else "fail",
    }
    summary_path = ROOT / "artifacts" / "phase-15" / "clean-clone-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
