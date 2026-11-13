"""Tests for handling UDP push events with MusicCastDevice.handle()."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiomusiccast_co.musiccast_device import MusicCastDevice

from .common import FakeYxc

DEVICE_ID = "00A0DE000000"


def event(**sections: Any) -> dict[str, Any]:
    """Return a UDP event as the device sends it, with its device_id."""
    return {**sections, "device_id": DEVICE_ID}


async def test_zone_state_is_applied(device: MusicCastDevice) -> None:
    await device.handle(event(main={"power": "on", "volume": 120, "mute": True}))

    main = device.data.zones["main"]
    assert (main.power, main.current_volume, main.mute) == ("on", 120, True)
    # actual_volume_db range is -80.5..16.5 in 0.5 steps: -80.5 + 120 * 0.5
    assert main.actual_volume == -20.5


async def test_zone_event_keeps_unmentioned_fields(device: MusicCastDevice) -> None:
    await device.handle(event(zone2={"mute": True}))

    zone2 = device.data.zones["zone2"]
    assert (zone2.power, zone2.current_volume, zone2.input, zone2.actual_volume) == ("standby", 81, "audio1", -40.0)


async def test_volume_event_without_actual_volume(device: MusicCastDevice) -> None:
    device.data.zones["main"].actual_volume = None

    await device.handle(event(main={"volume": 120}))

    assert device.data.zones["main"].actual_volume is None


async def test_event_for_unknown_zone_is_logged(device: MusicCastDevice, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        await device.handle(event(zone3={"power": "on"}))

    assert "Zone zone3 does not exist" in caplog.text


@pytest.mark.parametrize("flag", ["play_info_updated", "status_updated"])
async def test_zone_update_flags_refetch_the_zone(device: MusicCastDevice, yxc: FakeYxc, flag: str) -> None:
    yxc.update("main/getStatus", sound_program="straight")

    await device.handle(event(main={flag: True}))

    assert yxc.read_count("main/getStatus") == 1
    assert device.data.zones["main"].sound_program == "straight"


@pytest.mark.parametrize(
    ("section", "path"),
    [
        ({"netusb": {"play_info_updated": True}}, "netusb/getPlayInfo"),
        ({"netusb": {"preset_info_updated": True}}, "netusb/getPresetInfo"),
        ({"tuner": {"play_info_updated": True}}, "tuner/getPlayInfo"),
        ({"dist": {"dist_info_updated": True}}, "dist/getDistributionInfo"),
        ({"clock": {"settings_updated": True}}, "clock/getSettings"),
        ({"system": {"func_status_updated": True}}, "system/getFuncStatus"),
    ],
)
async def test_update_flags_refetch_their_source(
    full_device: MusicCastDevice, yxc: FakeYxc, section: dict[str, Any], path: str
) -> None:
    await full_device.handle(event(**section))

    assert yxc.read_count(path) == len(yxc.reads) == 1


async def test_netusb_play_time(device: MusicCastDevice, yxc: FakeYxc) -> None:
    await device.handle(event(netusb={"play_time": 42}))

    assert device.data.netusb_play_time == 42
    assert device.data.netusb_play_time_updated is not None
    assert yxc.reads == []


async def test_undecodable_event_refetches_everything(device: MusicCastDevice, yxc: FakeYxc) -> None:
    # MusicCastUdpProtocol passes None for a datagram that is not valid UTF-8 JSON.
    callback = MagicMock()
    device.register_callback(callback)
    yxc.update("main/getStatus", volume=100)

    await device.handle(None)

    assert device.data.zones["main"].current_volume == 100
    callback.assert_called_once_with()


async def test_callbacks_run_after_each_event(device: MusicCastDevice) -> None:
    callback = MagicMock()
    removed = MagicMock()
    device.register_callback(callback)
    device.register_callback(removed)
    device.remove_callback(removed)

    await device.handle(event(main={"mute": True}))

    callback.assert_called_once_with()
    removed.assert_not_called()


async def test_switching_to_mc_link_triggers_group_update(device: MusicCastDevice) -> None:
    reduce_by_source: list[bool] = []

    async def group_update() -> None:
        reduce_by_source.append(device.group_reduce_by_source)

    device.register_group_update_callback(group_update)

    await device.handle(event(main={"input": "mc_link"}))

    assert reduce_by_source == [False]
    assert device.data.zones["main"].input == "mc_link"


async def test_leaving_mc_link_marks_group_reduce_by_source(device: MusicCastDevice) -> None:
    device.data.zones["main"].input = "mc_link"
    reduce_by_source: list[bool] = []

    async def group_update() -> None:
        reduce_by_source.append(device.group_reduce_by_source)

    device.register_group_update_callback(group_update)

    await device.handle(event(main={"input": "hdmi1"}))

    assert reduce_by_source == [True]
    assert device.group_reduce_by_source is False


async def test_input_change_without_mc_link_does_not_trigger_group_update(device: MusicCastDevice) -> None:
    group_update = AsyncMock()
    device.register_group_update_callback(group_update)

    await device.handle(event(main={"input": "hdmi2"}))

    group_update.assert_not_awaited()
    assert device.data.zones["main"].input == "hdmi2"


async def test_input_change_during_group_update_does_not_trigger_group_update(device: MusicCastDevice) -> None:
    group_update = AsyncMock()
    device.register_group_update_callback(group_update)

    async with device.data.group_update_lock:
        await device.handle(event(main={"input": "mc_link"}))

    group_update.assert_not_awaited()


async def test_removed_group_update_callback_is_not_called(device: MusicCastDevice) -> None:
    group_update = AsyncMock()
    device.register_group_update_callback(group_update)
    device.remove_group_update_callback(group_update)

    await device.handle(event(main={"input": "mc_link"}))

    group_update.assert_not_awaited()
