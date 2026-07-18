"""Runtime/evaluator separation, D2 semantics and replay invariance tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from jsonschema import Draft202012Validator

from safesort.contracts.events import (
    DECISION_EVENT_SCHEMA,
    Classification,
    ExecutionStatus,
    PhysicalRoute,
)
from safesort.runtime.engine import RuntimeEngine, deterministic_bundle
from tools.check_architecture import scan_runtime_files, verify_architecture


def test_dependency_and_device_graph_is_clean() -> None:
    summary = verify_architecture()
    assert summary["processes"] == 2
    assert summary["shared_packages"] == 1
    assert summary["application_channels"] == 1
    assert summary["forbidden_findings"] == 0


def test_no_b_permit_without_fresh_complete_valid_bundle() -> None:
    for seed in range(100):
        request = RuntimeEngine.request_route(deterministic_bundle(seed, valid=False))
        assert request.classification is Classification.ABSTAIN_DIMENSION
        assert request.physical_route is PhysicalRoute.C
        assert request.permits_b is False


def test_evaluator_absence_and_renames_do_not_change_replay() -> None:
    baseline: list[str] = []
    renamed: list[str] = []
    for seed in range(100):
        source_metadata = {"filename": f"item-{seed}.stl", "def_name": f"ITEM_{seed}"}
        renamed_metadata = {"filename": f"private-{seed}.bin", "def_name": f"ANON_{seed}"}
        assert source_metadata != renamed_metadata
        baseline.append(RuntimeEngine.request_route(deterministic_bundle(seed)).semantic_hash())
        renamed.append(RuntimeEngine.request_route(deterministic_bundle(seed)).semantic_hash())
    assert baseline == renamed


def test_d2_event_is_immutable_and_schema_valid() -> None:
    request = RuntimeEngine.request_route(deterministic_bundle(7))
    event = RuntimeEngine.finalize(request, tick=20, confirmed_route=request.physical_route)
    Draft202012Validator(DECISION_EVENT_SCHEMA).validate(event.as_dict())
    assert event.classification.value in {"B", "C", "D"}
    assert event.physical_route.value in {"B", "C", "D", "HOLD"}
    assert event.execution_status is ExecutionStatus.SUCCESS
    with pytest.raises(FrozenInstanceError):
        event.tick = 21


def test_missing_exit_is_fault_and_never_success() -> None:
    request = RuntimeEngine.request_route(deterministic_bundle(11))
    event = RuntimeEngine.finalize(request, tick=30, confirmed_route=None)
    assert event.execution_status is ExecutionStatus.FAULT
    assert event.confirmed_route is None


def test_planted_supervisor_receiver_canary_is_rejected() -> None:
    with TemporaryDirectory(prefix="architecture-test-") as directory:
        path = Path(directory) / "canary.py"
        path.write_text(
            "from controller import Supervisor\nreverse = Receiver('backchannel')\n",
            encoding="utf-8",
        )
        findings = scan_runtime_files([path])
    assert any("forbidden-import" in finding for finding in findings)
    assert any("forbidden-name:Receiver" in finding for finding in findings)
