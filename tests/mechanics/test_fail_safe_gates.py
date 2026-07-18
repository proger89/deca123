from __future__ import annotations

import pytest

from safesort.contracts.events import Classification, PhysicalRoute
from safesort.runtime.mechanics import FailSafeRouter, GateParameters, RouteState, simulate_power_return


@pytest.mark.parametrize(
    ("classification", "route"),
    [
        (Classification.B, PhysicalRoute.B),
        (Classification.C, PhysicalRoute.C),
        (Classification.D, PhysicalRoute.D),
        (Classification.ABSTAIN_DIMENSION, PhysicalRoute.C),
        (Classification.ABSTAIN_SHAPE, PhysicalRoute.D),
    ],
)
def test_nominal_and_abstain_routes(classification: Classification, route: PhysicalRoute) -> None:
    router = FailSafeRouter()
    assert router.arm(classification) is route
    assert router.release() is route
    router.confirm_exit(route)
    assert router.state is RouteState.SUCCESS


def test_b_requires_both_position_permits() -> None:
    router = FailSafeRouter()
    router.arm(Classification.B)
    router.shape_position_confirmed = False
    with pytest.raises(RuntimeError, match="both position"):
        router.release()
    assert router.state is RouteState.FAULT


def test_power_loss_returns_to_passive_routes() -> None:
    for name, route in (("dimension", PhysicalRoute.C), ("shape", PhysicalRoute.D)):
        router = FailSafeRouter()
        router.arm(Classification.B)
        assert router.power_loss(name) is route
        assert not router.drive_enabled
        assert router.reset_required
        trace = simulate_power_return(GateParameters(name, route))
        assert trace.return_time_s <= 0.5


def test_estop_and_exit_mismatch_latch() -> None:
    router = FailSafeRouter()
    router.arm(Classification.B)
    router.release()
    router.emergency_stop(2)
    assert not router.drive_enabled and router.reset_required
    with pytest.raises(RuntimeError, match="reset"):
        router.arm(Classification.B)

    router.reset()
    router.arm(Classification.B)
    router.release()
    with pytest.raises(RuntimeError, match="matching exit"):
        router.confirm_exit(PhysicalRoute.C)
    assert router.state is RouteState.FAULT
