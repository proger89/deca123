"""Evaluator-only analytic truth; never imported by runtime code."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum


class ProxyType(StrEnum):
    BOX = "Box"
    CYLINDER = "Cylinder"
    CAPSULE = "Capsule"
    COMPOUND = "Compound"
    CONVEX_INDEXED_FACE_SET = "ConvexIndexedFaceSet"


@dataclass(frozen=True, slots=True)
class AnalyticShape:
    shape: ProxyType
    dimensions_mm: tuple[float, float, float]
    mass_kg: float


@dataclass(frozen=True, slots=True)
class OracleTruth:
    dimensions_mm: tuple[float, float, float]
    circularity_k: float
    volume_mm3: float
    center_of_mass_mm: tuple[float, float, float]
    inertia_kg_m2: tuple[float, float, float]


def exact_truth(shape: AnalyticShape) -> OracleTruth:
    x_mm, y_mm, z_mm = shape.dimensions_mm
    ordered = sorted((float(x_mm), float(y_mm), float(z_mm)), reverse=True)
    dimensions = (ordered[0], ordered[1], ordered[2])
    x, y, z = (value / 1000.0 for value in (x_mm, y_mm, z_mm))
    if shape.shape is ProxyType.BOX:
        volume = x_mm * y_mm * z_mm
        k_value = min(y_mm, z_mm) / math.hypot(y_mm, z_mm)
        inertia = (
            shape.mass_kg * (y * y + z * z) / 12.0,
            shape.mass_kg * (x * x + z * z) / 12.0,
            shape.mass_kg * (x * x + y * y) / 12.0,
        )
    elif shape.shape is ProxyType.CYLINDER:
        radius = y / 2.0
        volume = math.pi * (y_mm / 2.0) ** 2 * x_mm
        k_value = 1.0
        axial = shape.mass_kg * radius * radius / 2.0
        radial = shape.mass_kg * (3.0 * radius * radius + x * x) / 12.0
        inertia = (axial, radial, radial)
    elif shape.shape is ProxyType.CAPSULE:
        radius = y / 2.0
        cylinder_length_mm = max(0.0, x_mm - y_mm)
        volume = math.pi * (y_mm / 2.0) ** 2 * cylinder_length_mm + 4.0 * math.pi * (y_mm / 2.0) ** 3 / 3.0
        k_value = 1.0
        equivalent = shape.mass_kg * (radius * radius + x * x) / 5.0
        inertia = (shape.mass_kg * radius * radius / 2.0, equivalent, equivalent)
    else:
        raise ValueError("exact analytic truth supports Box, Cylinder and Capsule")
    return OracleTruth(dimensions, k_value, volume, (0.0, 0.0, 0.0), inertia)


def stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
