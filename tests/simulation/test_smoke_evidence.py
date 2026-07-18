"""Fast checks for physical smoke-scene and evidence semantics."""

from __future__ import annotations

import json
from pathlib import Path

from tools.smoke_cycle import ROOT, semantic_trace_hash, validate_scene


def test_official_smoke_scene_is_exact(tmp_path: Path) -> None:
    summary = validate_scene(ROOT / "scenarios/smoke/unknown_stl_b.yaml", tmp_path)
    assert summary["result"] == "pass"
    assert all(summary["checks"].values())
    assert (tmp_path / "top-view.svg").is_file()


def test_semantic_trace_hash_is_stable(tmp_path: Path) -> None:
    trace = tmp_path / "runtime-events.jsonl"
    rows = [
        {"event_type": "sensor_observation", "tick": 5, "dimensions_mm": [120.0, 60.0, 50.0]},
        {"event_type": "exit_observation", "tick": 10, "detected": True},
    ]
    trace.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    assert semantic_trace_hash(trace) == semantic_trace_hash(trace)
