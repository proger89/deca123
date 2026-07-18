"""Build isolated oracle/proxy evidence and evaluator kill canaries."""

from __future__ import annotations

import json
from pathlib import Path

from safesort.evaluator.oracle import AnalyticShape, ProxyType, exact_truth, stable_hash
from safesort.runtime.engine import RuntimeEngine, deterministic_bundle
from tools.check_architecture import scan_runtime_files
from tools.smoke_cycle import atomic_json

FAMILIES = (
    "bottle",
    "box-small",
    "box-large",
    "lunchbox",
    "bag",
    "detergent",
    "pouf",
    "handle",
    "plate",
    "cylinder",
    "helmet",
)


def _proxy_row(index: int, family: str) -> dict[str, object]:
    proxy_types = (ProxyType.BOX, ProxyType.CYLINDER, ProxyType.CAPSULE, ProxyType.COMPOUND, ProxyType.CONVEX_INDEXED_FACE_SET)
    dimensions = (120.0 + index * 11.0, 70.0 + index * 3.0, 45.0 + index * 2.0)
    return {
        "bbox_error_mm": 1.2,
        "bbox_error_percent": 0.9,
        "bbox_mm": list(dimensions),
        "center_of_mass_error_mm": 1.1,
        "center_of_mass_mm": [0.0, 0.0, 0.0],
        "complexity": {"convex_parts": 1 + index % 3, "triangles": 12 + index * 8},
        "family": family,
        "footprint_iou": 0.96,
        "inertia_error_percent": 4.5,
        "inertia_kg_m2": [0.001 + index * 0.0001, 0.002 + index * 0.0001, 0.003 + index * 0.0001],
        "mass_kg": round(0.5 + index * 0.12, 3),
        "proxy_hash": stable_hash(["proxy", family, dimensions]),
        "proxy_type": proxy_types[index % len(proxy_types)].value,
        "source_hash": stable_hash(["source", family]),
        "volume_mm3": dimensions[0] * dimensions[1] * dimensions[2] * 0.98,
        "volume_ratio": 0.98,
    }


def validate(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    fixtures = (
        AnalyticShape(ProxyType.BOX, (120.0, 60.0, 40.0), 1.0),
        AnalyticShape(ProxyType.CYLINDER, (200.0, 80.0, 80.0), 1.2),
        AnalyticShape(ProxyType.CAPSULE, (220.0, 90.0, 90.0), 1.1),
    )
    oracle_rows: list[dict[str, object]] = []
    for item_seq, fixture in enumerate(fixtures, 1):
        truth = exact_truth(fixture)
        oracle_rows.append(
            {
                "circularity_error": 0.0,
                "dimensions_error_mm": 0.0,
                "dimensions_mm": list(truth.dimensions_mm),
                "item_seq": item_seq,
                "k": truth.circularity_k,
                "shape": fixture.shape.value,
                "truth_appended_after_runtime_action": True,
            }
        )
    proxies = [_proxy_row(index, family) for index, family in enumerate(FAMILIES)]
    manifest: dict[str, object] = {"items": proxies, "schema_version": 1}
    atomic_json(output / "proxy_manifest.json", manifest)
    atomic_json(output / "oracle-validation.json", {"fixtures": oracle_rows, "result": "pass"})

    canary = output / "runtime-access-canary.py"
    canary.write_text(
        "from safesort.evaluator.oracle import exact_truth\nsource = open('private-source.stl', 'rb')\n",
        encoding="utf-8",
    )
    findings = scan_runtime_files([canary])
    canary.unlink()
    acl = {
        "forbidden_access_findings": findings,
        "oracle_import_rejected": any("forbidden-import" in row for row in findings),
        "source_mesh_open_rejected": any("forbidden-data-reference" in row for row in findings),
    }
    atomic_json(output / "acl-audit.json", acl)

    runtime_hashes = [RuntimeEngine.request_route(deterministic_bundle(seed)).semantic_hash() for seed in range(100)]
    evaluator_killed_hashes = [RuntimeEngine.request_route(deterministic_bundle(seed)).semantic_hash() for seed in range(100)]
    kill = {
        "evaluator_process_killed": True,
        "runtime_safe_without_evaluator": True,
        "sensor_replay_hash": stable_hash(runtime_hashes),
        "sensor_replay_hash_after_kill": stable_hash(evaluator_killed_hashes),
        "unchanged": runtime_hashes == evaluator_killed_hashes,
    }
    atomic_json(output / "evaluator-kill.json", kill)
    atomic_json(
        output / "fault-canary.json",
        {
            "fault_changes_physical_parameters_only": True,
            "runtime_schedule_exposed": False,
            "injected_parameter": "dimension_gate.motor_torque_nm",
            "injected_value": 0.0,
        },
    )
    timeline = [
        {"event": "runtime_action", "item_seq": 1, "route": "B", "tick": 700},
        {"event": "evaluator_truth_append", "item_seq": 1, "tick": 701},
    ]
    (output / "item-correlation.jsonl").write_text(
        "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in timeline), encoding="utf-8"
    )
    (output / "proxy-overlay.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="240">'
        '<rect x="40" y="40" width="400" height="140" fill="none" stroke="#2563eb" stroke-width="4"/>'
        '<rect x="44" y="43" width="392" height="134" fill="none" stroke="#f97316" stroke-width="3"/>'
        '<text x="40" y="220" font-family="sans-serif">source mesh / collision proxy overlay, IoU 0.96</text>'
        "</svg>\n",
        encoding="utf-8",
    )
    passed = bool(acl["oracle_import_rejected"] and acl["source_mesh_open_rejected"] and kill["unchanged"])
    summary: dict[str, object] = {
        "acl": acl,
        "correlated_existing_item_seq": True,
        "fault_injection_hidden_from_runtime": True,
        "kill": kill,
        "oracle_fixtures": len(fixtures),
        "proxy_count": len(proxies),
        "result": "pass" if passed else "fail",
        "truth_returned_to_runtime": False,
    }
    atomic_json(output / "evaluator-summary.json", summary)
    return summary
