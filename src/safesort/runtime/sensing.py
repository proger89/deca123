"""Same-tick, calibration-bound multi-view depth contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class ViewHealth(StrEnum):
    HEALTHY = "HEALTHY"
    MISSING = "MISSING"
    FROZEN = "FROZEN"
    LATE = "LATE"
    EMPTY = "EMPTY"


@dataclass(frozen=True, slots=True)
class ViewFrame:
    name: str
    tick: int
    encoder_tick: int
    sample_count: int
    finite_count: int
    depth_hash: str
    health: ViewHealth
    motion_compensation_mm: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "depth_hash": self.depth_hash,
            "encoder_tick": self.encoder_tick,
            "finite_count": self.finite_count,
            "health": self.health.value,
            "motion_compensation_mm": self.motion_compensation_mm,
            "name": self.name,
            "sample_count": self.sample_count,
            "tick": self.tick,
        }


@dataclass(frozen=True, slots=True)
class FrameBundle:
    tick: int
    encoder_tick: int
    encoder_position_rad: float
    calibration_hash: str
    seed: int
    enabled_views: tuple[str, ...]
    frames: tuple[ViewFrame, ...]
    valid: bool
    invalid_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        ticks = [frame.tick for frame in self.frames]
        return {
            "calibration_hash": self.calibration_hash,
            "enabled_views": list(self.enabled_views),
            "encoder_position_rad": self.encoder_position_rad,
            "encoder_tick": self.encoder_tick,
            "frames": [frame.as_dict() for frame in self.frames],
            "health_sequence": [frame.health.value for frame in self.frames],
            "invalid_reasons": list(self.invalid_reasons),
            "presence": {name: any(frame.name == name for frame in self.frames) for name in self.enabled_views},
            "seed": self.seed,
            "semantic_hash": self.semantic_hash(),
            "tick": self.tick,
            "timestamp_spread_ticks": max(ticks) - min(ticks) if ticks else 0,
            "valid": self.valid,
        }

    def semantic_hash(self) -> str:
        payload = {
            "calibration_hash": self.calibration_hash,
            "enabled_views": self.enabled_views,
            "encoder_position_rad": round(self.encoder_position_rad, 9),
            "encoder_tick": self.encoder_tick,
            "frames": [frame.as_dict() for frame in self.frames],
            "invalid_reasons": self.invalid_reasons,
            "seed": self.seed,
            "tick": self.tick,
            "valid": self.valid,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


def assemble_frame_bundle(
    frames: tuple[ViewFrame, ...],
    *,
    enabled_views: tuple[str, ...],
    tick: int,
    encoder_tick: int,
    encoder_position_rad: float,
    calibration_hash: str,
    seed: int,
) -> FrameBundle:
    by_name = {frame.name: frame for frame in frames}
    reasons: list[str] = []
    for name in enabled_views:
        frame = by_name.get(name)
        if frame is None:
            reasons.append(f"missing:{name}")
        elif frame.health is not ViewHealth.HEALTHY:
            reasons.append(f"health:{name}:{frame.health.value}")
        elif frame.tick != tick:
            reasons.append(f"tick:{name}:{frame.tick}")
        elif frame.encoder_tick != encoder_tick:
            reasons.append(f"encoder_tick:{name}:{frame.encoder_tick}")
    unexpected = sorted(set(by_name) - set(enabled_views))
    reasons.extend(f"unexpected:{name}" for name in unexpected)
    return FrameBundle(
        tick=tick,
        encoder_tick=encoder_tick,
        encoder_position_rad=encoder_position_rad,
        calibration_hash=calibration_hash,
        seed=seed,
        enabled_views=enabled_views,
        frames=frames,
        valid=not reasons,
        invalid_reasons=tuple(reasons),
    )
