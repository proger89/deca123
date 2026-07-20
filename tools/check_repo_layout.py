"""Validate the portable SafeSort repository skeleton."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".supergoal",
    ".venv",
    "materials",
    "tmp",
    "__pycache__",
}
REQUIRED_PATHS = (
    ".dockerignore",
    ".gitattributes",
    ".gitignore",
    "Dockerfile",
    "README.md",
    "assets/catalog.yaml",
    "assets/source-materials.sha256",
    "config/toolchain.lock.json",
    "criteria",
    "datasets",
    "docs/materials-audit.md",
    "docs/official-clarifications.md",
    "evidence",
    "run_scenario.py",
    "scenarios",
    "src/safesort/common",
    "src/safesort/contracts",
    "src/safesort/evaluator",
    "src/safesort/reporting",
    "src/safesort/runner",
    "src/safesort/runtime",
    "submission",
    "tests/smoke",
    "tools",
    "webots/controllers",
    "webots/protos",
    "webots/worlds",
)
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".dockerignore",
    ".gitattributes",
    ".gitignore",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
DEVELOPER_PATH = re.compile(r"(?i)(?:[a-z]:[\\/](?:users|hackatons|sites|new-projects)[\\/]|/home/[^/]+/)")
SECRET = re.compile(
    r"(?i)(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|"
    r"(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"][^'\"]{8,})"
)


def project_files() -> list[Path]:
    files: list[Path] = []
    for directory, child_directories, filenames in os.walk(ROOT):
        child_directories[:] = [name for name in child_directories if name not in EXCLUDED_PARTS]
        files.extend(Path(directory) / filename for filename in filenames)
    return files


def main() -> int:
    missing = [relative for relative in REQUIRED_PATHS if not (ROOT / relative).exists()]
    absolute_path_hits: list[str] = []
    secret_hits: list[str] = []

    for path in project_files():
        if path == Path(__file__).resolve():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative == "tools/polish_audit.py":
            # The audit implementation intentionally contains developer-path
            # regex literals; scanning that scanner would match its own rule.
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if DEVELOPER_PATH.search(content):
            absolute_path_hits.append(relative)
        if SECRET.search(content):
            secret_hits.append(relative)

    toolchain_path = ROOT / "config" / "toolchain.lock.json"
    toolchain_errors: list[str] = []
    if toolchain_path.exists():
        toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
        base_image = str(toolchain.get("docker_base", ""))
        if "@sha256:" not in base_image:
            toolchain_errors.append("container.base_image must use a sha256 digest")
        if any(word in base_image.lower() for word in (":latest", "nightly")):
            toolchain_errors.append("floating image tag is forbidden")

    result = {
        "absolute_developer_paths": sorted(absolute_path_hits),
        "missing": missing,
        "result": "pass" if not (missing or absolute_path_hits or secret_hits or toolchain_errors) else "fail",
        "secret_candidates": sorted(secret_hits),
        "toolchain_errors": toolchain_errors,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
