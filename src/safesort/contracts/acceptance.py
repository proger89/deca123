"""Machine-checkable acceptance contract and deterministic judge matrix."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "criteria" / "acceptance-contract.json"
SCHEMA_PATH = ROOT / "criteria" / "acceptance-contract.schema.json"
MATRIX_PATH = ROOT / "criteria" / "ACCEPTANCE_MATRIX.md"
LOCK_PATH = ROOT / "criteria" / "contract.lock.json"
CLARIFICATIONS_PATH = ROOT / "docs" / "official-clarifications.md"
SOURCE_MANIFEST_PATH = ROOT / "assets" / "source-materials.sha256"
EXPECTED_LABELS = ["OFFICIAL", "DERIVED", "TEAM_SLO", "STRETCH"]
EXPECTED_FAMILIES = {"PRE", "UGT", "CLS", "EXE", "PERF", "INT", "REP"}
LABEL_PREFIX = {
    "OFFICIAL": "official:",
    "DERIVED": "derived:",
    "TEAM_SLO": "team:",
    "STRETCH": "stretch:",
}

JsonObject = dict[str, Any]


class ContractError(RuntimeError):
    """Raised when the acceptance contract or its lock is invalid."""


def load_object(path: Path) -> JsonObject:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return cast(JsonObject, data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def schema_errors(data: JsonObject, schema: JsonObject) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:  # pragma: no cover - container always installs the lock
        raise ContractError("jsonschema==4.23.0 is required for contract validation") from error

    validator = Draft202012Validator(schema)
    return [
        f"schema:{'/'.join(str(part) for part in error.absolute_path)}:{error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.absolute_path))
    ]


def classify_official(dimensions_mm: Sequence[float], circularity_k: float) -> str:
    """Apply strict official priority: dimensions to C, then circularity to D/B."""
    if len(dimensions_mm) != 3:
        raise ValueError("dimensions_mm must contain length, width and height")
    minimum = (10.0, 10.0, 10.0)
    maximum = (450.0, 320.0, 320.0)
    if any(not (lower < float(value) < upper) for value, lower, upper in zip(dimensions_mm, minimum, maximum, strict=True)):
        return "C"
    return "D" if circularity_k > 0.8 else "B"


def official_accuracy(correct: int, total: int) -> float:
    if total <= 0 or correct < 0 or correct > total:
        raise ValueError("accuracy counts are invalid")
    return correct / total


def _source_manifest() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in SOURCE_MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        result[relative] = digest
    return result


def semantic_errors(data: JsonObject, *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    sections = cast(list[JsonObject], data.get("rubric_sections", []))
    requirements = cast(list[JsonObject], data.get("requirements", []))
    families = cast(list[JsonObject], data.get("scenario_families", []))
    fixtures = cast(list[JsonObject], data.get("fixtures", []))

    if len(sections) != 7:
        errors.append(f"semantic:rubric_sections expected 7, got {len(sections)}")
    point_total = sum(int(section.get("points", 0)) for section in sections)
    if point_total != 130:
        errors.append(f"semantic:rubric points expected 130, got {point_total}")

    family_ids = {str(family.get("id", "")) for family in families}
    if family_ids != EXPECTED_FAMILIES:
        errors.append(f"semantic:scenario families {sorted(family_ids)} are incomplete")
    for family in families:
        if not str(family.get("evidence_owner", "")):
            errors.append(f"semantic:family {family.get('id')} has no evidence owner")

    requirement_ids = [str(requirement.get("id", "")) for requirement in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("semantic:duplicate requirement ID")
    assigned_ids = [
        str(requirement_id) for section in sections for requirement_id in cast(list[object], section.get("requirement_ids", []))
    ]
    if sorted(assigned_ids) != sorted(requirement_ids):
        errors.append("semantic:rubric mapping must assign every requirement exactly once")

    observed_labels: set[str] = set()
    for requirement in requirements:
        requirement_id = str(requirement.get("id", "unknown"))
        label = str(requirement.get("label", ""))
        source_ref = str(requirement.get("source_ref", ""))
        observed_labels.add(label)
        expected_prefix = LABEL_PREFIX.get(label)
        if expected_prefix is None or not source_ref.startswith(expected_prefix):
            errors.append(f"semantic:{requirement_id} label {label} contradicts source {source_ref}")
        if str(requirement.get("family", "")) not in family_ids:
            errors.append(f"semantic:{requirement_id} references an unknown family")
        if not str(requirement.get("scenario_id", "")):
            errors.append(f"semantic:{requirement_id} has no scenario")
        if not isinstance(requirement.get("numeric_gate"), dict):
            errors.append(f"semantic:{requirement_id} has no numeric gate")
        if not str(requirement.get("artifact_path", "")):
            errors.append(f"semantic:{requirement_id} has no artifact")
    if observed_labels != set(EXPECTED_LABELS):
        errors.append("semantic:not all provenance labels are exercised")

    fixture_ids = [str(fixture.get("id", "")) for fixture in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)):
        errors.append("semantic:duplicate fixture ID")
    fixture_kinds = {str(fixture.get("kind", "")) for fixture in fixtures}
    required_kinds = {
        "classification",
        "private_stl",
        "flow",
        "fault",
        "isolation",
        "reproducibility",
        "metric",
    }
    if not required_kinds.issubset(fixture_kinds):
        errors.append("semantic:mandatory fixture families are incomplete")
    for fixture in fixtures:
        if fixture.get("kind") != "classification":
            continue
        inputs = cast(JsonObject, fixture.get("input", {}))
        expected = cast(JsonObject, fixture.get("expected", {}))
        actual = classify_official(cast(list[float], inputs.get("dimensions_mm", [])), float(inputs.get("k", 0.0)))
        if actual != expected.get("classification"):
            errors.append(f"semantic:{fixture.get('id')} expected {expected}, got {actual}")

    semantics = cast(JsonObject, data.get("outcome_semantics", {}))
    required_semantics = {
        "abstain_counts_as_wrong": True,
        "safe_reject_is_success": False,
        "success_requires_confirmed_exit": True,
        "ground_truth_after_runtime_action": True,
    }
    for key, expected_value in required_semantics.items():
        if semantics.get(key) is not expected_value:
            errors.append(f"semantic:{key} must be {expected_value}")

    manifest = _source_manifest()
    for source in cast(list[JsonObject], data.get("sources", [])):
        relative = str(source.get("path", ""))
        expected_hash = str(source.get("sha256", ""))
        if relative.startswith("materials/"):
            actual_hash = manifest.get(relative)
        else:
            source_path = root / relative
            actual_hash = sha256_file(source_path) if source_path.is_file() else None
        if actual_hash != expected_hash:
            errors.append(f"semantic:source hash mismatch for {relative}")
    return errors


def gate_text(gate: JsonObject) -> str:
    return f"{gate['metric']} {gate['operator']} {gate['threshold']}"


def render_matrix(data: JsonObject) -> str:
    lines = [
        "# Locked acceptance and evidence matrix",
        "",
        f"Contract: `{data['contract_id']}`  ",
        f"Locked: `{data['locked_at']}`  ",
        "Generated file: edit `criteria/acceptance-contract.json`, then regenerate.",
        "",
        "## Rubric coverage",
        "",
        "| Section | Points | Scenario | Numeric gate | Artifact |",
        "|---|---:|---|---|---|",
    ]
    for section in cast(list[JsonObject], data["rubric_sections"]):
        lines.append(
            f"| {section['id']} — {section['title']} | {section['points']} | "
            f"`{section['scenario_id']}` | `{gate_text(cast(JsonObject, section['numeric_gate']))}` | "
            f"`{section['artifact_path']}` |"
        )
    lines.extend(
        [
            "| **Total** | **130** | | | |",
            "",
            "## Requirement contract",
            "",
            "| ID | Label | Scenario | Numeric gate | Evidence artifact |",
            "|---|---|---|---|---|",
        ]
    )
    for requirement in cast(list[JsonObject], data["requirements"]):
        lines.append(
            f"| {requirement['id']} | {requirement['label']} | `{requirement['scenario_id']}` | "
            f"`{gate_text(cast(JsonObject, requirement['numeric_gate']))}` | "
            f"`{requirement['artifact_path']}` |"
        )
    semantics = cast(JsonObject, data["outcome_semantics"])
    lines.extend(
        [
            "",
            "## Locked semantics",
            "",
            "- Dimension checks are strict and run before circularity: equality routes to C.",
            "- Circularity uses `K = r_inscribed / R_circumscribed`; only `K > 0.8` routes to D.",
            f"- Abstain counts as wrong in official accuracy: `{semantics['abstain_counts_as_wrong']}`.",
            f"- SAFE_REJECT is SUCCESS: `{semantics['safe_reject_is_success']}`.",
            f"- SUCCESS requires confirmed exit: `{semantics['success_requires_confirmed_exit']}`.",
            "",
            "## Fixture and provenance totals",
            "",
            f"- Fixtures: {len(cast(list[object], data['fixtures']))}",
            f"- Scenario families: {len(cast(list[object], data['scenario_families']))}",
            f"- Hashed official sources: {len(cast(list[object], data['sources']))}",
            "",
        ]
    )
    return "\n".join(lines)


def expected_lock(matrix_text: str, *, root: Path = ROOT) -> JsonObject:
    return {
        "schema_version": 1,
        "acceptance_contract_sha256": sha256_file(root / CONTRACT_PATH.relative_to(ROOT)),
        "acceptance_schema_sha256": sha256_file(root / SCHEMA_PATH.relative_to(ROOT)),
        "clarifications_sha256": sha256_file(root / CLARIFICATIONS_PATH.relative_to(ROOT)),
        "rendered_matrix_sha256": sha256_text(matrix_text),
        "source_manifest_sha256": sha256_file(root / SOURCE_MANIFEST_PATH.relative_to(ROOT)),
    }


def validate_contract_data(data: JsonObject, *, root: Path = ROOT, check_lock: bool = True) -> list[str]:
    schema = load_object(root / SCHEMA_PATH.relative_to(ROOT))
    errors = schema_errors(data, schema)
    errors.extend(semantic_errors(data, root=root))
    if check_lock:
        matrix_path = root / MATRIX_PATH.relative_to(ROOT)
        lock_path = root / LOCK_PATH.relative_to(ROOT)
        if not matrix_path.is_file() or not lock_path.is_file():
            errors.append("lock:rendered matrix or contract lock is missing")
        else:
            matrix_text = matrix_path.read_text(encoding="utf-8")
            actual_lock = load_object(lock_path)
            if actual_lock != expected_lock(matrix_text, root=root):
                errors.append("lock:contract/source/clarification/rendered hashes changed")
    return errors


def planted_label_canary_fails(data: JsonObject, *, root: Path = ROOT) -> bool:
    canary = deepcopy(data)
    requirements = cast(list[JsonObject], canary["requirements"])
    team_requirement = next(item for item in requirements if item["label"] == "TEAM_SLO")
    team_requirement["label"] = "OFFICIAL"
    errors = validate_contract_data(canary, root=root, check_lock=False)
    return any("contradicts source" in error for error in errors)


def validate_contract(*, root: Path = ROOT) -> JsonObject:
    data = load_object(root / CONTRACT_PATH.relative_to(ROOT))
    errors = validate_contract_data(data, root=root)
    if errors:
        raise ContractError("\n".join(errors))
    if not planted_label_canary_fails(data, root=root):
        raise ContractError("planted TEAM_SLO-as-OFFICIAL canary unexpectedly passed")
    sections = cast(list[JsonObject], data["rubric_sections"])
    fixtures = cast(list[JsonObject], data["fixtures"])
    return {
        "canary_rejected": True,
        "contract_id": data["contract_id"],
        "fixture_count": len(fixtures),
        "requirement_count": len(cast(list[object], data["requirements"])),
        "rubric_points": sum(int(section["points"]) for section in sections),
        "rubric_sections": len(sections),
        "source_count": len(cast(list[object], data["sources"])),
    }
