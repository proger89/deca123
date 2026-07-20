from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from typing import Any, cast

import pytest

from tools import release_check


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, capture_output=True, check=True, text=True)


def _fixture_repo(path: Path) -> None:
    path.mkdir()
    (path / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    (path / "run_scenario.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import json
            import subprocess
            from pathlib import Path

            output = Path("artifacts/release-check")
            output.mkdir(parents=True, exist_ok=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True
            ).stdout.strip()
            hashes = ["same-semantic-hash"] * 3
            summary = {"result": "pass", "semantic_hashes": hashes}
            manifest = {
                "commit": revision,
                "dirty": False,
                "network": "none",
                "repeat": 3,
                "semantic_hashes": hashes,
                "source_event_hash": "same-source-event-hash",
            }
            (output / "release-summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (output / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    _run(["git", "init", "--quiet"], path)
    _run(["git", "config", "user.name", "Release Test"], path)
    _run(["git", "config", "user.email", "release-test@example.invalid"], path)
    _run(["git", "add", "."], path)
    _run(["git", "commit", "--quiet", "-m", "fixture"], path)


def test_release_check_repeats_from_clean_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    _fixture_repo(repo)
    monkeypatch.setattr(release_check, "ROOT", repo)

    result = cast(dict[str, Any], release_check.run_release_check(2, clean_clone=True))

    assert result["result"] == "pass"
    assert result["root_clean"] is True
    assert result["cross_clone_semantic_identical"] is True
    assert result["cross_clone_event_identical"] is True
    assert len(result["clean_clones"]) == 2
    assert all(run["manifest_bound_to_clone"] is True for run in result["clean_clones"])


def test_release_check_rejects_dirty_source_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    _fixture_repo(repo)
    (repo / "run_scenario.py").write_text(
        (repo / "run_scenario.py").read_text(encoding="utf-8") + "\n# uncommitted\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_check, "ROOT", repo)

    result = cast(dict[str, Any], release_check.run_release_check(1, clean_clone=True))

    assert result["result"] == "fail"
    assert result["root_clean"] is False
