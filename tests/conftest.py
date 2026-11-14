"""Fixtures for the aiomusiccast_co tests."""

from __future__ import annotations

import pytest

from aiomusiccast_co.list_navigation import ListNavigator
from aiomusiccast_co.musiccast_device import MusicCastDevice

from .common import FakeYxc, add_missing_features, create_device, load_device_fixtures


@pytest.fixture(autouse=True)
def fast_list_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read list info without pauses while walking a list, and give up on an unreachable layer quickly."""
    monkeypatch.setattr(ListNavigator, "POLL_INTERVAL", 0)
    monkeypatch.setattr(ListNavigator, "STEP_TIMEOUT", 0.1)


@pytest.fixture
def yxc() -> FakeYxc:
    """Return a fake YXC API answering with the responses captured from an RX-A4A."""
    return FakeYxc(load_device_fixtures("rx_a4a"))


@pytest.fixture
async def device(yxc: FakeYxc) -> MusicCastDevice:
    """Return the captured RX-A4A, fetched once."""
    return await create_device(yxc)


@pytest.fixture
async def full_device(yxc: FakeYxc) -> MusicCastDevice:
    """Return the RX-A4A with the features it lacks added (see ``add_missing_features``), fetched once."""
    add_missing_features(yxc)
    return await create_device(yxc)
