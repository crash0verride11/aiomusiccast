"""Tests for MusicCast group (distribution) management."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from aiomusiccast_co.const import NULL_GROUP
from aiomusiccast_co.exceptions import MusicCastGroupException
from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.pyamaha import Dist, Zone

from .common import FakeYxc, Write

GROUP = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
SERVER_IP = "192.0.2.10"
CLIENT_A = "192.0.2.21"
CLIENT_B = "192.0.2.22"
DIST_EVENT = {"dist": {"dist_info_updated": True}}


@pytest.fixture
def no_udp_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the one-second wait for a UDP update, so a missing update falls back to a manual fetch at once."""

    async def wait(_self: MusicCastDevice, checks: list[Callable[[], bool]]) -> None:
        if not all(check() for check in checks):
            raise TimeoutError

    monkeypatch.setattr(MusicCastDevice, "wait_for_data_update", wait)


def on(
    yxc: FakeYxc,
    url: str,
    *,
    dist: dict[str, Any] | None = None,
    push: dict[str, Any] | None = None,
    device: Any = None,
) -> None:
    """Play the device's reaction to the write to ``url``: update its distribution info and push a UDP event."""
    previous = yxc.on_write

    async def react(write: Write) -> None:
        if previous is not None:
            await previous(write)
        if (write[0] if isinstance(write, tuple) else write) != url:
            return
        if dist is not None:
            yxc.update("dist/getDistributionInfo", **dist)
        if push is not None:
            await device.handle(push)

    yxc.on_write = react


def server_dist(*clients: str) -> dict[str, Any]:
    return {
        "group_id": GROUP,
        "role": "server",
        "server_zone": "main",
        "client_list": [{"ip_address": ip, "data_type": "base"} for ip in clients],
    }


async def group_server(device: MusicCastDevice, yxc: FakeYxc, *clients: str) -> None:
    """Make the device the server of a group with ``clients``."""
    yxc.update("dist/getDistributionInfo", **server_dist(*clients))
    await device._fetch_distribution_data()


# -- server ---------------------------------------------------------------------------------------------------------


async def test_server_group_extend(device: MusicCastDevice, yxc: FakeYxc) -> None:
    set_server = Dist.set_server_info(GROUP, "main", "add", [CLIENT_A])
    on(yxc, set_server[0], dist=server_dist(CLIENT_A), push=DIST_EVENT, device=device)

    await device.mc_server_group_extend("main", [CLIENT_A], GROUP, 1)

    assert yxc.writes == [set_server, Dist.start_distribution(1)]
    assert (device.data.group_role, device.data.group_client_list) == ("server", [CLIENT_A])


async def test_server_group_extend_waits_for_a_late_udp_update(device: MusicCastDevice, yxc: FakeYxc) -> None:
    set_server = Dist.set_server_info(GROUP, "main", "add", [CLIENT_A])

    async def late_update(write: Write) -> None:
        if isinstance(write, tuple) and write[0] == set_server[0]:
            yxc.update("dist/getDistributionInfo", **server_dist(CLIENT_A))
            asyncio.get_running_loop().call_later(0.15, lambda: asyncio.ensure_future(device.handle(DIST_EVENT)))

    yxc.on_write = late_update

    await device.mc_server_group_extend("main", [CLIENT_A], GROUP, 1)

    assert device.data.group_client_list == [CLIENT_A]
    assert yxc.read_count("dist/getDistributionInfo") == 1


@pytest.mark.usefixtures("no_udp_wait")
async def test_server_group_extend_falls_back_to_manual_fetch(
    device: MusicCastDevice, yxc: FakeYxc, caplog: pytest.LogCaptureFixture
) -> None:
    set_server = Dist.set_server_info(GROUP, "main", "add", [CLIENT_A])
    on(yxc, set_server[0], dist=server_dist(CLIENT_A))

    with caplog.at_level(logging.WARNING):
        await device.mc_server_group_extend("main", [CLIENT_A], GROUP, 1)

    assert "did not receive the expected group data update" in caplog.text
    assert device.data.group_client_list == [CLIENT_A]
    assert len(yxc.writes) == 2


async def test_server_group_reduce_restarts_distribution_for_remaining_clients(
    device: MusicCastDevice, yxc: FakeYxc
) -> None:
    await group_server(device, yxc, CLIENT_A, CLIENT_B)
    set_server = Dist.set_server_info(GROUP, "main", "remove", [CLIENT_B])
    on(yxc, set_server[0], dist=server_dist(CLIENT_A), push=DIST_EVENT, device=device)

    await device.mc_server_group_reduce("main", [CLIENT_B], 2)

    assert yxc.writes == [set_server, Dist.start_distribution(2)]


async def test_server_group_reduce_by_all_clients(device: MusicCastDevice, yxc: FakeYxc) -> None:
    await group_server(device, yxc, CLIENT_A)
    set_server = Dist.set_server_info(GROUP, "main", "remove", [CLIENT_A])
    on(yxc, set_server[0], dist=server_dist(), push=DIST_EVENT, device=device)

    await device.mc_server_group_reduce("main", [CLIENT_A], 2)

    assert yxc.writes == [set_server]


async def test_server_group_close(device: MusicCastDevice, yxc: FakeYxc) -> None:
    await group_server(device, yxc, CLIENT_A)
    closed = {"group_id": NULL_GROUP, "role": "none", "client_list": []}
    on(yxc, Dist.set_server_info("")[0], dist=closed, push=DIST_EVENT, device=device)

    await device.mc_server_group_close()

    assert yxc.writes == [Dist.stop_distribution(), Dist.set_server_info("")]
    assert device.data.group_id == NULL_GROUP


# -- client ---------------------------------------------------------------------------------------------------------


async def test_client_join(device: MusicCastDevice, yxc: FakeYxc) -> None:
    set_client = Dist.set_client_info(GROUP, ["main"], SERVER_IP)
    set_input = Zone.set_input("main", "mc_link", "")
    on(yxc, set_client[0], dist={"group_id": GROUP, "role": "client"}, push=DIST_EVENT, device=device)
    on(yxc, set_input, push={"main": {"input": "mc_link"}}, device=device)

    await device.mc_client_join(SERVER_IP, GROUP, "main")

    assert yxc.writes == [set_client, set_input]
    assert (device.data.group_id, device.data.zones["main"].input) == (GROUP, "mc_link")


async def test_client_unjoin(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.update("dist/getDistributionInfo", group_id=GROUP, role="client")
    await device._fetch_distribution_data()
    on(yxc, Dist.set_client_info("")[0], dist={"group_id": NULL_GROUP, "role": "none"}, push=DIST_EVENT, device=device)

    await device.mc_client_unjoin()

    assert yxc.writes == [Dist.set_client_info("")]
    assert device.data.group_id == NULL_GROUP


# -- zones of the same device ---------------------------------------------------------------------------------------


async def test_zone_join(device: MusicCastDevice, yxc: FakeYxc) -> None:
    set_input = Zone.set_input("zone2", "mc_link", "")
    on(yxc, set_input, push={"zone2": {"input": "mc_link"}}, device=device)

    await device.zone_join("zone2")

    assert yxc.writes == [set_input]


async def test_zone_unjoin_restores_a_save_input_and_turns_the_zone_off(device: MusicCastDevice, yxc: FakeYxc) -> None:
    zone2 = device.data.zones["zone2"]
    zone2.input, zone2.power = "mc_link", "on"
    turn_off = Zone.set_power("zone2", "standby")
    on(yxc, turn_off, push={"zone2": {"power": "standby"}}, device=device)

    await device.zone_unjoin("zone2")

    assert yxc.writes == [Zone.set_input("zone2", device.get_save_inputs("zone2")[0], ""), turn_off]


async def test_zone_unjoin_without_save_input(
    device: MusicCastDevice, yxc: FakeYxc, caplog: pytest.LogCaptureFixture
) -> None:
    device.data.zones["zone2"].input_list = ["mc_link"]

    with caplog.at_level(logging.WARNING):
        await device.zone_unjoin("zone2")

    assert "did not find a save input for zone zone2" in caplog.text
    assert yxc.writes == [Zone.set_power("zone2", "standby")]


# -- failures -------------------------------------------------------------------------------------------------------

GroupCall = Callable[[MusicCastDevice], Coroutine[Any, Any, None]]


@pytest.mark.parametrize(
    ("call", "writes_per_try"),
    [
        (lambda device: device.mc_server_group_extend("main", [CLIENT_B], GROUP, 1), 2),
        (lambda device: device.mc_server_group_reduce("main", [CLIENT_A], 1), 1),
        (lambda device: device.mc_server_group_close(), 2),
        (lambda device: device.mc_client_join(SERVER_IP, GROUP, "main"), 2),
        (lambda device: device.mc_client_unjoin(), 1),
        (lambda device: device.zone_join("zone2"), 1),
        (lambda device: device.zone_unjoin("zone2"), 2),
    ],
)
@pytest.mark.usefixtures("no_udp_wait")
async def test_group_change_is_retried_once_then_raises(
    device: MusicCastDevice, yxc: FakeYxc, call: GroupCall, writes_per_try: int
) -> None:
    # The device never confirms the change: no UDP event and unchanged distribution info.
    await group_server(device, yxc, CLIENT_A)
    device.data.zones["zone2"].power = "on"
    yxc.reads.clear()

    with pytest.raises(MusicCastGroupException):
        await call(device)

    assert len(yxc.writes) == 2 * writes_per_try
    assert yxc.read_count("dist/getDistributionInfo") == 2
