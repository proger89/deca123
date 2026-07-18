"""Same-tick sensing contract and health transition tests."""

from __future__ import annotations

from dataclasses import replace

from safesort.runtime.sensing import ViewFrame, ViewHealth, assemble_frame_bundle

VIEWS = ("top", "left", "right", "front", "rear")


def healthy_frames() -> tuple[ViewFrame, ...]:
    return tuple(
        ViewFrame(
            name=name,
            tick=5,
            encoder_tick=5,
            sample_count=64,
            finite_count=32,
            depth_hash=f"{index:064x}",
            health=ViewHealth.HEALTHY,
        )
        for index, name in enumerate(VIEWS, start=1)
    )


def bundle(frames: tuple[ViewFrame, ...]):
    return assemble_frame_bundle(
        frames,
        enabled_views=VIEWS,
        tick=5,
        encoder_tick=5,
        encoder_position_rad=0.16,
        calibration_hash="a" * 64,
        seed=501,
    )


def test_complete_same_tick_bundle_is_valid_and_stable() -> None:
    first = bundle(healthy_frames())
    second = bundle(healthy_frames())
    assert first.valid is True
    assert first.as_dict()["timestamp_spread_ticks"] == 0
    assert first.semantic_hash() == second.semantic_hash()


def test_missing_view_never_relabels_stale_data() -> None:
    result = bundle(healthy_frames()[:-1])
    assert result.valid is False
    assert result.invalid_reasons == ("missing:rear",)


def test_frozen_and_late_views_invalidate_bundle() -> None:
    frames = healthy_frames()
    frozen = bundle((replace(frames[0], health=ViewHealth.FROZEN), *frames[1:]))
    late = bundle((frames[0], replace(frames[1], tick=4, health=ViewHealth.LATE), *frames[2:]))
    assert frozen.valid is False
    assert late.valid is False
    assert "health:top:FROZEN" in frozen.invalid_reasons
    assert "health:left:LATE" in late.invalid_reasons
