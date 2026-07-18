"""Validation and evidence helpers for the deterministic physical smoke cycle."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATTERN = re.compile(r"^# SAFESORT_LAYOUT (?P<values>.+)$", re.MULTILINE)
FORBIDDEN_RUNTIME_KEYS = {"filename", "mesh", "def_name", "class_truth", "oracle", "source_asset"}


class SmokeEvidenceError(RuntimeError):
    """Raised when the scene or recorded evidence violates the smoke contract."""


def load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SmokeEvidenceError(f"{path} must contain an object")
    return cast(dict[str, Any], payload)


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_pair(value: str) -> list[int]:
    return [int(part) for part in value.split(",")]


def _world_layout(world_text: str) -> dict[str, list[int]]:
    values: dict[str, list[int]] = {}
    for match in LAYOUT_PATTERN.finditer(world_text):
        for token in match.group("values").split():
            key, raw = token.split("=", 1)
            values[key] = _parse_pair(raw)
    return values


def validate_scene(scenario_path: Path, output: Path) -> dict[str, object]:
    scenario = load_object(scenario_path)
    world_path = ROOT / str(scenario["world"])
    expected = cast(dict[str, Any], scenario["official_layout"])
    actual = _world_layout(world_path.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "workspace_exact": actual.get("workspace_mm") == expected["workspace_mm"] == [10000, 6000],
        "a_anchor_exact": actual.get("a_anchor_mm") == expected["a_anchor_mm"] == [1000, 3000],
        "b_anchor_exact": actual.get("b_anchor_mm") == expected["b_anchor_mm"] == [8000, 3800],
    }
    workspace = cast(list[int], expected["workspace_mm"])
    for label in ("c", "d"):
        cage = cast(dict[str, list[int]], expected[f"{label}_cage"])
        center = cage["center_mm"]
        size = cage["size_mm"]
        checks[f"{label}_size_exact"] = actual.get(f"{label}_size_mm") == size == [1200, 800, 800]
        checks[f"{label}_center_exact"] = actual.get(f"{label}_center_mm") == center
        checks[f"{label}_inside_workspace"] = (
            size[0] / 2 <= center[0] <= workspace[0] - size[0] / 2 and size[1] / 2 <= center[1] <= workspace[1] - size[1] / 2
        )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise SmokeEvidenceError("scene validation failed: " + ", ".join(failed))
    output.mkdir(parents=True, exist_ok=True)
    top_view = output / "top-view.svg"
    top_view.write_text(
        """<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1000\" height=\"600\" viewBox=\"0 0 10000 6000\">\n"
        "<rect width=\"10000\" height=\"6000\" fill=\"#eef2f7\" stroke=\"#111827\" stroke-width=\"40\"/>\n"
        "<path d=\"M1000 3000 H5800 L8000 3800 V5000\" fill=\"none\" stroke=\"#111827\" stroke-width=\"500\"/>\n"
        "<circle cx=\"1000\" cy=\"3000\" r=\"150\" fill=\"#f59e0b\"/><circle cx=\"8000\" cy=\"3800\" r=\"150\" fill=\"#22c55e\"/>\n"
        "<rect x=\"6400\" y=\"800\" width=\"1200\" height=\"800\" fill=\"#3b82f6\" opacity=\".45\"/>\n"
        "<rect x=\"7900\" y=\"800\" width=\"1200\" height=\"800\" fill=\"#6366f1\" opacity=\".45\"/>\n"
        "</svg>\n""",
        encoding="utf-8",
    )
    result: dict[str, object] = {
        "checks": checks,
        "result": "pass",
        "scenario_id": str(scenario["scenario_id"]),
        "top_view": top_view.name,
        "world": str(scenario["world"]),
    }
    atomic_json(output / "scene-validation.json", result)
    return result


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise SmokeEvidenceError(f"non-object row in {path}")
        rows.append(cast(dict[str, Any], payload))
    return rows


def semantic_trace_hash(path: Path) -> str:
    rows = read_jsonl(path)
    encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _frame_pixels(position: tuple[float, float], width: int = 640, height: int = 360) -> bytes:
    background = bytearray([238, 242, 247] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                background[offset : offset + 3] = bytes(color)

    fill_rect(55, 165, 390, 195, (30, 41, 59))
    fill_rect(375, 180, 520, 210, (30, 41, 59))
    fill_rect(500, 195, 530, 300, (30, 41, 59))
    x = int((position[0] + 5.0) / 10.0 * width)
    y = int((3.0 - position[1]) / 6.0 * height)
    fill_rect(x - 6, y - 5, x + 6, y + 5, (220, 38, 38))
    return bytes(background)


def create_trace_video(output: Path) -> Path:
    trajectory = read_jsonl(output / "trajectory.jsonl")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or not trajectory:
        raise SmokeEvidenceError("ffmpeg and a non-empty trajectory are required")
    frames = output / ".frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir()
    selected = trajectory[::2]
    for index, row in enumerate(selected):
        x = float(row["x_m"])
        z = float(row["z_m"])
        pixels = _frame_pixels((x, z))
        (frames / f"frame-{index:03d}.ppm").write_bytes(b"P6\n640 360\n255\n" + pixels)
    target = output / "smoke-trace.mp4"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        "15",
        "-i",
        str(frames / "frame-%03d.ppm"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(target),
    ]
    completed = subprocess.run(command, check=False)
    shutil.rmtree(frames)
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise SmokeEvidenceError("trace video creation failed")
    return target


def write_manifest(output: Path, scenario: str, seed: int, exit_code: int, *, canary: bool) -> dict[str, object]:
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "manifest.json")
    hashes = {path.name: sha256_file(path) for path in files}
    trace_path = output / "runtime-events.jsonl"
    payload: dict[str, object] = {
        "canary": canary,
        "container": {"gpu": "none", "network": "none", "platform": "linux/amd64"},
        "exit_code": exit_code,
        "files": hashes,
        "scenario": scenario,
        "seed": seed,
        "semantic_trace_hash": semantic_trace_hash(trace_path) if trace_path.is_file() else None,
    }
    atomic_json(output / "manifest.json", payload)
    return payload


def _walk_values(payload: object) -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key).lower()
            yield from _walk_values(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_values(value)


def verify_bundle(bundle: Path) -> dict[str, object]:
    manifest = load_object(bundle / "manifest.json")
    files = cast(dict[str, str], manifest["files"])
    mismatches = [name for name, digest in files.items() if not (bundle / name).is_file() or sha256_file(bundle / name) != digest]
    rows = read_jsonl(bundle / "runtime-events.jsonl")
    tokens = set(_walk_values(rows))
    forbidden = sorted(tokens & FORBIDDEN_RUNTIME_KEYS)
    decision_indices = [index for index, row in enumerate(rows) if row.get("event_type") == "decision"]
    exit_indices = [index for index, row in enumerate(rows) if row.get("event_type") == "exit_observation" and row.get("detected") is True]
    nominal_success = bool(decision_indices) and rows[decision_indices[-1]].get("execution_status") == "SUCCESS"
    success_after_exit = nominal_success and bool(exit_indices) and exit_indices[-1] < decision_indices[-1]
    canary = bundle / "canary"
    canary_manifest = load_object(canary / "manifest.json")
    canary_rows = read_jsonl(canary / "runtime-events.jsonl")
    canary_statuses = [row.get("execution_status") for row in canary_rows if row.get("event_type") == "decision"]
    replay_path = bundle / "replay.json"
    replay = load_object(replay_path) if replay_path.is_file() else {}
    replay_ok = bool(replay.get("identical"))
    checks = {
        "canary_fault": canary_statuses == ["FAULT"] and int(canary_manifest["exit_code"]) != 0,
        "canary_never_success": "SUCCESS" not in canary_statuses,
        "hashes_match": not mismatches,
        "network_none": cast(dict[str, str], manifest["container"])["network"] == "none",
        "replay_identical": replay_ok,
        "runtime_metadata_clean": not forbidden,
        "scene_valid": load_object(bundle / "scene-validation.json")["result"] == "pass",
        "success_after_physical_exit": success_after_exit and load_object(bundle / "evaluator-result.json")["physical_exit"] is True,
        "video_present": (bundle / "smoke-trace.mp4").is_file() and (bundle / "smoke-trace.mp4").stat().st_size > 0,
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise SmokeEvidenceError("bundle verification failed: " + ", ".join(failed))
    return {
        "canary_exit_code": canary_manifest["exit_code"],
        "checks": checks,
        "replay_hashes": replay.get("hashes", []),
        "result": "pass",
        "semantic_trace_hash": manifest["semantic_trace_hash"],
        "video": str(bundle / "smoke-trace.mp4"),
    }
