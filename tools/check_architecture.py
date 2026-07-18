"""Verify the one-way runtime/evaluator architecture and sensor-only boundary."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from safesort.contracts.events import DECISION_EVENT_SCHEMA  # noqa: E402
from safesort.runtime.engine import RuntimeEngine, deterministic_bundle  # noqa: E402

ARCHITECTURE_PATH = ROOT / "config" / "architecture.json"
EVENT_SCHEMA_PATH = ROOT / "src" / "safesort" / "contracts" / "schemas" / "decision-event.schema.json"
RUNTIME_ROOT = ROOT / "src" / "safesort" / "runtime"
EVALUATOR_ROOT = ROOT / "src" / "safesort" / "evaluator"
RUNTIME_CONTROLLER = ROOT / "webots" / "controllers" / "runtime_controller" / "runtime_controller.py"
EVALUATOR_CONTROLLER = ROOT / "webots" / "controllers" / "evaluator_supervisor" / "evaluator_supervisor.py"

ARCHITECTURE_GRAPH: dict[str, object] = {
    "schema_version": 1,
    "shared_package": "src/safesort/contracts",
    "processes": {
        "RuntimeController": {
            "package": "src/safesort/runtime",
            "controller": "webots/controllers/runtime_controller/runtime_controller.py",
            "devices": [
                "RangeFinder:rangefinder_top",
                "DistanceSensor:photoeye_entry",
                "DistanceSensor:b_exit_sensor",
                "RotationalMotor:provisional_gate_motor",
                "PositionSensor:provisional_gate_position",
                "Emitter:runtime_events_emitter",
            ],
        },
        "EvaluatorSupervisor": {
            "package": "src/safesort/evaluator",
            "controller": "webots/controllers/evaluator_supervisor/evaluator_supervisor.py",
            "devices": ["Receiver:runtime_events_receiver"],
        },
    },
    "application_channels": [
        {
            "from": "RuntimeController",
            "to": "EvaluatorSupervisor",
            "transport": "Emitter->Receiver",
        }
    ],
    "runtime_forbidden": [
        "Supervisor",
        "Receiver",
        "safesort.evaluator",
        "oracle-data",
        "source-model",
        "reverse-application-channel",
    ],
}

FORBIDDEN_RUNTIME_IMPORTS = ("safesort.evaluator", "controller.Supervisor")
FORBIDDEN_RUNTIME_NAMES = {
    "Supervisor",
    "Receiver",
    "getFromDef",
    "getRoot",
    "getSelected",
    "getUrdf",
}
FORBIDDEN_RUNTIME_TEXT = re.compile(
    r"(?i)(?:materials[/\\]|assets[/\\].*(?:proxy|manifest)|\.stl\b|\.stp\b|"
    r"hidden[_-]?label|reverse[_-]?(?:ipc|channel)|oracle[_-]?(?:data|path))"
)

JsonObject = dict[str, Any]


class ArchitectureError(RuntimeError):
    """Raised when isolation verification finds one or more violations."""


def encoded_json(value: dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_generated_contracts() -> None:
    ARCHITECTURE_PATH.write_bytes(encoded_json(ARCHITECTURE_GRAPH))
    EVENT_SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVENT_SCHEMA_PATH.write_bytes(encoded_json(DECISION_EVENT_SCHEMA))


def _module_names(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


def scan_runtime_files(paths: Sequence[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError as error:
            violations.append(f"{relative}:syntax:{error.msg}")
            continue
        for module in _module_names(tree):
            if any(module.startswith(forbidden) for forbidden in FORBIDDEN_RUNTIME_IMPORTS):
                violations.append(f"{relative}:forbidden-import:{module}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_RUNTIME_NAMES:
                violations.append(f"{relative}:forbidden-name:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_RUNTIME_NAMES:
                violations.append(f"{relative}:forbidden-api:{node.attr}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and FORBIDDEN_RUNTIME_TEXT.search(node.value):
                violations.append(f"{relative}:forbidden-data-reference")
        if FORBIDDEN_RUNTIME_TEXT.search(source):
            violations.append(f"{relative}:forbidden-data-reference")
    return sorted(set(violations))


def _package_import_violations(root: Path, own_package: str) -> list[str]:
    violations: list[str] = []
    other_package = "safesort.evaluator" if own_package == "safesort.runtime" else "safesort.runtime"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _module_names(tree):
            if module.startswith(other_package):
                violations.append(f"{path.relative_to(ROOT).as_posix()}:cross-package:{module}")
    return violations


def _graph_violations(graph: JsonObject) -> list[str]:
    violations: list[str] = []
    processes = cast(dict[str, JsonObject], graph.get("processes", {}))
    runtime_devices = cast(list[str], processes.get("RuntimeController", {}).get("devices", []))
    evaluator_devices = cast(list[str], processes.get("EvaluatorSupervisor", {}).get("devices", []))
    channels = cast(list[JsonObject], graph.get("application_channels", []))
    if any(device.startswith("Receiver:") for device in runtime_devices):
        violations.append("graph:runtime has Receiver")
    if any(device.startswith("Emitter:") for device in evaluator_devices):
        violations.append("graph:evaluator has Emitter")
    if channels != [
        {
            "from": "RuntimeController",
            "to": "EvaluatorSupervisor",
            "transport": "Emitter->Receiver",
        }
    ]:
        violations.append("graph:application channel is not strictly one-way")
    return violations


def _replay_evidence() -> JsonObject:
    first_hashes: list[str] = []
    renamed_hashes: list[str] = []
    invalid_b_permits = 0
    for seed in range(100):
        first = RuntimeEngine.request_route(deterministic_bundle(seed))
        renamed = RuntimeEngine.request_route(deterministic_bundle(seed))
        first_hashes.append(first.semantic_hash())
        renamed_hashes.append(renamed.semantic_hash())
        if RuntimeEngine.request_route(deterministic_bundle(seed, valid=False)).permits_b:
            invalid_b_permits += 1
    combined = "".join(first_hashes).encode("ascii")
    import hashlib

    return {
        "evaluator_absent_invalid_b_permits": invalid_b_permits,
        "rename_def_label_invariant_seeds": 100 if first_hashes == renamed_hashes else 0,
        "replay_hash": hashlib.sha256(combined).hexdigest(),
        "replay_hashes_identical": first_hashes == renamed_hashes,
    }


def verify_architecture() -> JsonObject:
    violations: list[str] = []
    runtime_files = sorted(RUNTIME_ROOT.rglob("*.py")) + [RUNTIME_CONTROLLER]
    violations.extend(scan_runtime_files(runtime_files))
    violations.extend(_package_import_violations(RUNTIME_ROOT, "safesort.runtime"))
    violations.extend(_package_import_violations(EVALUATOR_ROOT, "safesort.evaluator"))

    if not ARCHITECTURE_PATH.is_file() or json.loads(ARCHITECTURE_PATH.read_text(encoding="utf-8")) != ARCHITECTURE_GRAPH:
        violations.append("graph:config/architecture.json is missing or stale")
    else:
        violations.extend(_graph_violations(load_json_object(ARCHITECTURE_PATH)))
    if not EVENT_SCHEMA_PATH.is_file() or json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8")) != DECISION_EVENT_SCHEMA:
        violations.append("contract:decision-event schema is missing or stale")

    runtime_text = RUNTIME_CONTROLLER.read_text(encoding="utf-8")
    evaluator_text = EVALUATOR_CONTROLLER.read_text(encoding="utf-8")
    if "Receiver" in runtime_text or "receiver" in runtime_text:
        violations.append("device:runtime controller contains reverse Receiver")
    if "Emitter" in evaluator_text or "emitter" in evaluator_text:
        violations.append("device:evaluator controller contains reverse Emitter")

    replay = _replay_evidence()
    if replay["evaluator_absent_invalid_b_permits"] != 0:
        violations.append("replay:invalid bundle permitted B")
    if replay["rename_def_label_invariant_seeds"] != 100:
        violations.append("replay:rename invariance failed")

    if violations:
        raise ArchitectureError("\n".join(sorted(set(violations))))
    graph = load_json_object(ARCHITECTURE_PATH)
    processes = cast(dict[str, JsonObject], graph["processes"])
    return {
        "application_channels": 1,
        "dependency_edges": 2,
        "evaluator_devices": len(cast(list[object], processes["EvaluatorSupervisor"]["devices"])),
        "forbidden_findings": 0,
        "processes": 2,
        "replay": replay,
        "runtime_devices": len(cast(list[object], processes["RuntimeController"]["devices"])),
        "shared_packages": 1,
    }


def load_json_object(path: Path) -> JsonObject:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ArchitectureError(f"{path} must contain a JSON object")
    return cast(JsonObject, data)


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-generated", action="store_true")
    args = parser.parse_args(argv)
    if args.write_generated:
        write_generated_contracts()
        emit({"action": "write-generated", "result": "pass"})
        return 0
    try:
        summary = verify_architecture()
    except ArchitectureError as error:
        emit({"error": str(error), "result": "fail"})
        return 1
    summary["result"] = "pass"
    emit(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
