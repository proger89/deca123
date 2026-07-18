"""Contract, official boundary and honest-metric regression tests."""

from __future__ import annotations

from typing import cast

from safesort.contracts.acceptance import (
    CONTRACT_PATH,
    JsonObject,
    classify_official,
    load_object,
    official_accuracy,
    planted_label_canary_fails,
    render_matrix,
    validate_contract,
    validate_contract_data,
)


def test_contract_schema_semantics_and_lock() -> None:
    summary = validate_contract()
    assert summary["rubric_sections"] == 7
    assert summary["rubric_points"] == 130
    assert summary["canary_rejected"] is True


def test_all_locked_classification_boundaries() -> None:
    contract = load_object(CONTRACT_PATH)
    fixtures = cast(list[JsonObject], contract["fixtures"])
    boundary_fixtures = [fixture for fixture in fixtures if fixture["kind"] == "classification"]
    assert len(boundary_fixtures) == 22
    for fixture in boundary_fixtures:
        inputs = cast(JsonObject, fixture["input"])
        expected = cast(JsonObject, fixture["expected"])
        assert classify_official(inputs["dimensions_mm"], inputs["k"]) == expected["classification"]


def test_strict_thresholds_and_dimension_priority() -> None:
    assert classify_official([10.0, 100.0, 100.0], 0.5) == "C"
    assert classify_official([450.0, 100.0, 100.0], 0.99) == "C"
    assert classify_official([100.0, 100.0, 100.0], 0.799) == "B"
    assert classify_official([100.0, 100.0, 100.0], 0.800) == "B"
    assert classify_official([100.0, 100.0, 100.0], 0.801) == "D"
    assert classify_official([450.01, 100.0, 100.0], 0.99) == "C"


def test_abstain_remains_in_official_denominator() -> None:
    assert official_accuracy(correct=8, total=10) == 0.8


def test_planted_slo_as_official_is_rejected() -> None:
    contract = load_object(CONTRACT_PATH)
    assert planted_label_canary_fails(contract)


def test_mandatory_fixture_families_and_owners() -> None:
    contract = load_object(CONTRACT_PATH)
    assert validate_contract_data(contract) == []
    fixtures = cast(list[JsonObject], contract["fixtures"])
    kinds = {fixture["kind"] for fixture in fixtures}
    assert {"private_stl", "flow", "fault", "isolation", "reproducibility"} <= kinds
    assert all(fixture["evidence_owner"] for fixture in fixtures)


def test_render_is_deterministic() -> None:
    contract = load_object(CONTRACT_PATH)
    assert render_matrix(contract) == render_matrix(load_object(CONTRACT_PATH))
