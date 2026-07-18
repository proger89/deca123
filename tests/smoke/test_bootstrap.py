"""Bootstrap invariants that must hold before feature work starts."""

from __future__ import annotations

import json
from pathlib import Path

import safesort

ROOT = Path(__file__).resolve().parents[2]


def test_package_version_is_explicit() -> None:
    assert safesort.__version__ == "0.1.0"


def test_toolchain_is_cpu_pinned() -> None:
    lock = json.loads((ROOT / "config" / "toolchain.lock.json").read_text(encoding="utf-8"))
    assert lock["platform"] == "linux/amd64"
    assert lock["python"] == "3.12.10"
    assert lock["webots"] == "R2025a"
    assert "@sha256:" in lock["docker_base"]
    assert "latest" not in lock["docker_base"].lower()


def test_source_materials_remain_unpublished() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "materials/**" in ignore
