"""Run repository privacy, secret, licence and release-cleanliness audits."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".runtime", ".supergoal", ".venv", "artifacts", "materials", "__pycache__"}
TEXT_SUFFIXES = {"", ".css", ".dockerignore", ".gitattributes", ".gitignore", ".html", ".ini", ".js", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
SECRET = re.compile(r"(?i)(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"][^'\"]{8,})")
PERSONAL = re.compile(r"(?i)(?:[A-Z]:[\\/](?:Users|hackatons|sites|new-projects)[\\/]|/home/[^/]+/)")
SESSION_MARKER = re.compile(r"(?m)(?:\bTODO\b|\bFIXME\b|console\.(?:log|error)\s*\(|\bprint\s*\()")


def project_files() -> list[Path]:
    files: list[Path] = []
    for directory, children, names in os.walk(ROOT):
        children[:] = [name for name in children if name not in EXCLUDED]
        files.extend(Path(directory) / name for name in names)
    return files


def main() -> int:
    findings: dict[str, list[str]] = {"absolute_paths": [], "personal_data": [], "secrets": [], "session_markers": []}
    for path in project_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in {"tools/check_repo_layout.py", "tools/polish_audit.py"} or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PERSONAL.search(content):
            findings["absolute_paths"].append(relative)
            findings["personal_data"].append(relative)
        if SECRET.search(content):
            findings["secrets"].append(relative)
        if SESSION_MARKER.search(content):
            findings["session_markers"].append(relative)
    licence_ok = (ROOT / "LICENSE").is_file() and "license" in (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    dependency_ok = (ROOT / "uv.lock").is_file() and "@sha256:" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    network_ok = "--network\",\n            \"none" in (ROOT / "run_scenario.py").read_text(encoding="utf-8")
    high_count = sum(len(values) for values in findings.values()) + int(not licence_ok) + int(not dependency_ok) + int(not network_ok)
    result = {
        "dependency_lock": dependency_ok,
        "findings": {key: sorted(set(value)) for key, value in findings.items()},
        "high_findings": high_count,
        "licence_declared": licence_ok,
        "runtime_network_disabled": network_ok,
        "result": "pass" if high_count == 0 else "fail",
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
