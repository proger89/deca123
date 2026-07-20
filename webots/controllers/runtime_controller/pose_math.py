"""Dependency-free RangeFinder pose transformations used by Webots controllers."""

from __future__ import annotations

import math

Vector3 = tuple[float, float, float]
AxisAngle = tuple[float, float, float, float]


def rotate_axis_angle(vector: Vector3, rotation: AxisAngle) -> Vector3:
    """Rotate ``vector`` with a normalized Rodrigues axis-angle transform."""

    x, y, z = vector
    axis_x, axis_y, axis_z, angle = rotation
    norm = math.sqrt(axis_x * axis_x + axis_y * axis_y + axis_z * axis_z)
    if norm <= 1e-12 or abs(angle) <= 1e-12:
        return vector
    axis_x /= norm
    axis_y /= norm
    axis_z /= norm
    cosine = math.cos(angle)
    sine = math.sin(angle)
    dot = axis_x * x + axis_y * y + axis_z * z
    cross_x = axis_y * z - axis_z * y
    cross_y = axis_z * x - axis_x * z
    cross_z = axis_x * y - axis_y * x
    one_minus_cosine = 1.0 - cosine
    return (
        x * cosine + cross_x * sine + axis_x * dot * one_minus_cosine,
        y * cosine + cross_y * sine + axis_y * dot * one_minus_cosine,
        z * cosine + cross_z * sine + axis_z * dot * one_minus_cosine,
    )


def rangefinder_point_to_world(
    translation_m: Vector3,
    rotation_axis_angle: AxisAngle,
    local_sample_m: Vector3,
) -> Vector3:
    """Project an image sample into world coordinates.

    ``local_sample_m`` stores image-right, image-up and positive measured depth.
    Webots RangeFinder looks along local ``-Z``, hence the sign conversion before
    applying the device pose.
    """

    horizontal, vertical, depth = local_sample_m
    rotated = rotate_axis_angle((horizontal, vertical, -depth), rotation_axis_angle)
    return (
        translation_m[0] + rotated[0],
        translation_m[1] + rotated[1],
        translation_m[2] + rotated[2],
    )
