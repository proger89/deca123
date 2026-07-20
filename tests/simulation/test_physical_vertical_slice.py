"""Static and geometry canaries for the real Webots vertical slice."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path

import pytest

from safesort.runtime.geometry import GeometryEstimator, GeometryFrameBundle, MeasurementStatus
from safesort.runtime.sensing import FrameBundle, ViewFrame, ViewHealth
from safesort.runtime.uncertainty import SafetyBands, conservative_decision
from tools.smoke_cycle import ROOT, validate_scene

VIEWS = ("top", "left", "right", "front", "rear")


def _pose_math_module():
    path = ROOT / "webots/controllers/runtime_controller/pose_math.py"
    spec = importlib.util.spec_from_file_location("safesort_webots_pose_math", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sync_bundle() -> FrameBundle:
    frames = tuple(
        ViewFrame(name, 5, 5, 256, 256, f"{index:064x}", ViewHealth.HEALTHY)
        for index, name in enumerate(VIEWS, 1)
    )
    return FrameBundle(5, 5, 0.0, "a" * 64, 7, VIEWS, frames, True, ())


def _horizontal_cylinder() -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for layer in range(25):
        x = -60.0 + 120.0 * layer / 24.0
        for index in range(96):
            angle = 2.0 * math.pi * index / 96.0
            points.append((x, 40.0 * math.cos(angle), 40.0 * math.sin(angle)))
    return tuple(points)


def test_circle_not_visible_from_top_still_routes_d() -> None:
    points = _horizontal_cylinder()
    top_visible = tuple(point for point in points if point[1] >= 39.0)
    top_x_span = max(point[0] for point in top_visible) - min(point[0] for point in top_visible)
    top_z_span = max(point[2] for point in top_visible) - min(point[2] for point in top_visible)
    assert min(top_x_span, top_z_span) / max(top_x_span, top_z_span) < 0.8
    top_set = set(top_visible)
    other = tuple(point for point in points if point not in top_set)
    views = (top_visible,) + tuple(tuple(other[index::4]) for index in range(4))
    geometry = GeometryEstimator.measure(
        GeometryFrameBundle(_sync_bundle(), views, 1.0, True, 0.0),
        calibration_hash="a" * 64,
    )
    assert geometry.status is MeasurementStatus.OK
    assert geometry.circularity_k is not None and geometry.circularity_k > 0.95
    assert geometry.circular_plane is not None and geometry.circular_plane.startswith("YZ@")
    decision = conservative_decision(
        geometry.dimensions_mm,
        geometry.circularity_k,
        measurement_status=geometry.status,
        bands=SafetyBands(),
    )
    assert decision.physical_route.value == "D"


def test_evaluator_has_no_physics_mutation_api() -> None:
    path = ROOT / "webots/controllers/evaluator_supervisor/evaluator_supervisor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called_attributes.isdisjoint(
        {
            "setSFVec3f",
            "setSFRotation",
            "setVelocity",
            "addForce",
            "addForceWithOffset",
            "addTorque",
            "resetPhysics",
        }
    )


def test_webots_video_provenance_cannot_label_schematic_fallback_physical(tmp_path: Path) -> None:
    smoke_cycle = (ROOT / "tools/smoke_cycle.py").read_text(encoding="utf-8")
    evaluator = (ROOT / "webots/controllers/evaluator_supervisor/evaluator_supervisor.py").read_text(
        encoding="utf-8"
    )
    assert '"source": "webots-rendering"' in evaluator
    assert '"physics_mutation": False' in evaluator
    assert '"schematic": False' in evaluator
    assert "Webots Camera.saveImage" in evaluator
    assert 'name "evidence_camera"' in (ROOT / "webots/protos/SorterCell.proto").read_text(encoding="utf-8")
    assert "capture_path.unlink(missing_ok=True)" in smoke_cycle

    # A non-Webots file may still be useful locally, but its manifest must not
    # make the physical-evidence claim consumed by release_bundle.py.
    (tmp_path / "trajectory.jsonl").write_text(
        '{"tick":1,"x_m":0.0,"z_m":0.0}\n', encoding="utf-8"
    )
    (tmp_path / "smoke-trace.mp4").write_bytes(b"schematic")
    from tools.smoke_cycle import write_manifest

    manifest = write_manifest(tmp_path, "scenario.yaml", 1907, 0, canary=False)
    assert "video_capture" not in manifest


def test_all_rangefinders_use_calibrated_local_minus_z_axis() -> None:
    calibration = json.loads((ROOT / "config/calibration/calibration.yaml").read_text(encoding="utf-8"))
    proto = (ROOT / "webots/protos/SorterCell.proto").read_text(encoding="utf-8")
    pose_math = _pose_math_module()
    expected_forward = {
        "top": (0.0, -1.0, 0.0),
        "left": (0.0, 0.0, 1.0),
        "right": (0.0, 0.0, -1.0),
        "front": (1.0, 0.0, 0.0),
        "rear": (-1.0, 0.0, 0.0),
    }
    assert calibration["axes"]["sensor_forward"] == "-Z"
    assert calibration["axes"]["webots_device_adapter_axis_angle"] == pytest.approx(
        [-0.577350269, 0.577350269, 0.577350269, 2.094395102]
    )
    assert proto.count("rotation -0.577350269 0.577350269 0.577350269 2.094395102") == 5
    for name, expected in expected_forward.items():
        view = calibration["views"][name]
        origin = tuple(float(value) for value in view["translation_m"])
        rotation = tuple(float(value) for value in view["rotation_axis_angle"])
        projected = pose_math.rangefinder_point_to_world(origin, rotation, (0.0, 0.0, 1.0))
        direction = tuple(projected[index] - origin[index] for index in range(3))
        assert direction == pytest.approx(expected, abs=5e-6)
        assert f'name "rangefinder_{name}"' in proto


def test_runtime_does_not_read_item_identity_or_mesh_metadata() -> None:
    runtime = (ROOT / "webots/controllers/runtime_controller/runtime_controller.py").read_text(encoding="utf-8").lower()
    for forbidden in ("source_asset", "itemmeshurl", "filename", "fixture-7f3a", "expectedroute"):
        assert forbidden not in runtime


def test_cylinder_stl_is_closed_and_outward_facing() -> None:
    lines = (ROOT / "assets/smoke/anonymous_cylinder.stl").read_text(encoding="ascii").splitlines()
    vertices = [
        tuple(float(value) for value in line.split()[1:])
        for line in lines
        if line.strip().startswith("vertex ")
    ]
    assert len(vertices) == 32 * 4 * 3
    edge_counts: dict[tuple[tuple[float, ...], tuple[float, ...]], int] = {}
    for index in range(0, len(vertices), 3):
        a, b, c = vertices[index : index + 3]
        ab = tuple(b[axis] - a[axis] for axis in range(3))
        ac = tuple(c[axis] - a[axis] for axis in range(3))
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        centroid = tuple((a[axis] + b[axis] + c[axis]) / 3.0 for axis in range(3))
        if a[0] == b[0] == c[0]:
            assert normal[0] * centroid[0] > 0.0
        else:
            assert normal[1] * centroid[1] + normal[2] * centroid[2] > 0.0
        for start, end in ((a, b), (b, c), (c, a)):
            edge = tuple(sorted((start, end)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    assert set(edge_counts.values()) == {2}


def test_missing_exit_fault_cannot_commit_a_detected_route() -> None:
    runtime = (ROOT / "webots/controllers/runtime_controller/runtime_controller.py").read_text(encoding="utf-8")
    assert "if disable_exit:" in runtime
    assert "physical_exit = None" in runtime
    assert '"fault-injection-missing-exit-confirmation"' in runtime


def test_runtime_uses_five_depth_views_and_physical_devices() -> None:
    runtime = (ROOT / "webots/controllers/runtime_controller/runtime_controller.py").read_text(encoding="utf-8")
    world = (ROOT / "webots/protos/SorterCell.proto").read_text(encoding="utf-8")
    assert "GeometryEstimator.measure" in runtime
    assert "max(observations, key=lambda observation: observation.silhouette_k)" in runtime
    assert '"method": "five-view-circle-fit-radial-contour"' in runtime
    assert '"source_views": list(PRIMARY_VIEWS)' in runtime
    assert 'by_name["top"].silhouette_k' not in runtime
    for view in VIEWS:
        assert f'rangefinder_{view}' in world
    assert world.count("Track {") >= 4
    assert world.count("LinearMotor {") >= 4
    assert "dimension_gate_motor" in world
    assert "shape_gate_motor" in world
    assert "springConstant 24" in world
    for route in ("b", "c", "d"):
        assert f'{route}_exit_sensor' in world


def test_b_c_d_worlds_preserve_official_layout(tmp_path: Path) -> None:
    for route in ("b", "c", "d"):
        scenario = ROOT / f"scenarios/smoke/unknown_stl_{route}.yaml"
        summary = validate_scene(scenario, tmp_path / route)
        assert summary["result"] == "pass"
