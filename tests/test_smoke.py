"""Smoke tests for aiomusiccast_co.

These run without a device: they cover the public API surface, the YXC URL builders and building capabilities from
pre-populated device data.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import aiomusiccast_co
from aiomusiccast_co.capabilities import BinarySetter, NumberSetter, Scene
from aiomusiccast_co.capability_registry import build_zone_capabilities
from aiomusiccast_co.exceptions import (
    MusicCastConnectionException,
    MusicCastResponseException,
    MusicCastUnsupportedException,
)
from aiomusiccast_co.features import DeviceFeature, ZoneFeature
from aiomusiccast_co.musiccast_data import MusicCastZoneData, RangeStep
from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.pyamaha import System, Zone

BASE = "http://{host}/YamahaExtendedControl/v1"


def test_public_api() -> None:
    for name in aiomusiccast_co.__all__:
        assert hasattr(aiomusiccast_co, name)
    assert isinstance(aiomusiccast_co.__version__, str)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (Zone.set_surround_ai("main", True), f"{BASE}/main/setSurroundAI?enable=true"),
        (Zone.set_surround_ai("zone2", False), f"{BASE}/zone2/setSurroundAI?enable=false"),
        (Zone.recall_scene("main", 3), f"{BASE}/main/recallScene?num=3"),
        (Zone.get_scene_info("main"), f"{BASE}/main/getSceneInfo"),
        (Zone.get_scene_info("main", 2), f"{BASE}/main/getSceneInfo?num=2"),
    ],
)
def test_zone_urls(url: str, expected: str) -> None:
    assert url == expected


@pytest.fixture
async def device() -> MusicCastDevice:
    """Return a device with surround AI, scenes and dB volume."""
    dev = MusicCastDevice("192.0.2.1", MagicMock())
    dev.device.get = AsyncMock()
    dev.device.request = AsyncMock()
    dev.device.post = AsyncMock()

    zone = MusicCastZoneData()
    zone.features = ZoneFeature.SURROUND_AI | ZoneFeature.SCENE | ZoneFeature.ACTUAL_VOLUME
    zone.surround_ai = True
    zone.scene_information = {1: "Movie", 2: "Music"}
    zone.min_volume = 0
    zone.actual_volume = -40.0
    zone.range_step["actual_volume_db"] = RangeStep(minimum=-80.5, maximum=16.5, step=0.5)
    dev.data.zones["main"] = zone
    return dev


async def test_build_zone_capabilities(device: MusicCastDevice) -> None:
    caps = {cap.id: cap for cap in build_zone_capabilities(device, "main")}

    surround_ai = caps["zone_SURROUND_AI"]
    assert isinstance(surround_ai, BinarySetter)
    assert surround_ai.current is True

    actual_volume = caps["zone_ACTUAL_VOLUME"]
    assert isinstance(actual_volume, NumberSetter)
    assert actual_volume.current == -40.0
    assert (actual_volume.value_range.minimum, actual_volume.value_range.maximum) == (-80.5, 16.5)

    scenes = [cap for cap in caps.values() if isinstance(cap, Scene)]
    assert sorted(scene.name for scene in scenes) == ["1: Movie", "2: Music"]


async def test_scene_activate_recalls_its_own_number(device: MusicCastDevice) -> None:
    scenes = {cap.name: cap for cap in build_zone_capabilities(device, "main") if isinstance(cap, Scene)}

    # Scene 1 is created first; a late-binding lambda would recall the last scene (2) instead.
    await scenes["1: Movie"].activate()

    device.device.get.assert_awaited_once_with(Zone.recall_scene("main", 1))


async def test_set_scene_info_posts_name(device: MusicCastDevice) -> None:
    await device.set_scene_info("main", 2, "Party")

    device.device.post.assert_awaited_once_with(f"{BASE}/main/setSceneInfo", {"num": 2, "text": "Party"})


async def test_set_volume_db_converts_to_volume_step(device: MusicCastDevice) -> None:
    await device.set_volume_db("main", -40.0)

    device.device.request.assert_awaited_once_with(Zone.set_volume("main", 81, 1))


async def test_unsupported_feature_raises(device: MusicCastDevice) -> None:
    device.data.zones["main"].features = ZoneFeature.NONE

    with pytest.raises(MusicCastUnsupportedException):
        await device.set_surround_ai("main", True)


async def test_failed_scene_fetch_keeps_previous_names(device: MusicCastDevice) -> None:
    device.device.request_json = AsyncMock(
        side_effect=[
            {"response_code": 0, "scene_list": [{"num": 1, "text": "Movie"}, {"num": 2, "text": "Music"}]},
            {"response_code": 5},
        ]
    )
    await device._fetch_scenes("main")
    scenes = [cap for cap in build_zone_capabilities(device, "main") if isinstance(cap, Scene)]

    await device._fetch_scenes("main")

    assert device.data.zones["main"].scene_information == {1: "Movie", 2: "Music"}
    assert sorted(scene.name for scene in scenes) == ["1: Movie", "2: Music"]


async def test_scene_fetch_applies_renamed_scenes(device: MusicCastDevice) -> None:
    scenes = [cap for cap in build_zone_capabilities(device, "main") if isinstance(cap, Scene)]
    device.device.request_json = AsyncMock(
        return_value={"response_code": 0, "scene_list": [{"num": 1, "text": "Movie"}, {"num": 2, "text": "Party"}]}
    )

    await device._fetch_scenes("main")

    assert sorted(scene.name for scene in scenes) == ["1: Movie", "2: Party"]


async def test_scene_name_falls_back_for_unknown_number(device: MusicCastDevice) -> None:
    scenes = [cap for cap in build_zone_capabilities(device, "main") if isinstance(cap, Scene)]

    device.data.zones["main"].scene_information = {}
    assert sorted(scene.name for scene in scenes) == ["1: Scene 1", "2: Scene 2"]

    device.data.zones["main"].scene_information = None
    assert sorted(scene.name for scene in scenes) == ["1: Scene 1", "2: Scene 2"]


ERROR_RESPONSE = {"response_code": 5}


@pytest.mark.parametrize(
    ("method", "attr", "value"),
    [
        ("_fetch_netusb", "netusb_total_time", 200),
        ("_fetch_netusb_presets", "netusb_preset_list", {1: ("spotify", "Morning")}),
        ("_fetch_tuner", "band", "fm"),
        ("_fetch_distribution_data", "group_id", "abc123"),
        ("_fetch_clock_data", "alarm_on", True),
        ("_fetch_func_status", "speaker_pattern", 2),
    ],
)
async def test_failed_poll_keeps_device_data(device: MusicCastDevice, method: str, attr: str, value: object) -> None:
    device.features |= DeviceFeature.SPEAKER_PATTERN
    setattr(device.data, attr, value)
    group_update = AsyncMock()
    device.register_group_update_callback(group_update)
    device.device.request_json = AsyncMock(return_value=ERROR_RESPONSE)

    await getattr(device, method)()

    assert getattr(device.data, attr) == value
    group_update.assert_not_awaited()


async def test_failed_zone_poll_keeps_zone_data(device: MusicCastDevice) -> None:
    zone = device.data.zones["main"]
    zone.power = "on"
    zone.input = "hdmi1"
    device.device.request_json = AsyncMock(return_value=ERROR_RESPONSE)

    await device._fetch_zone("main")

    assert (zone.power, zone.input, zone.surround_ai) == ("on", "hdmi1", True)


async def test_failed_setup_read_raises_and_is_retried(device: MusicCastDevice) -> None:
    device.device.request_json = AsyncMock(side_effect=[{"response_code": 0, "network_name": "Living"}, ERROR_RESPONSE])

    # A subclass of MusicCastConnectionException, so consumers' existing handling turns it into a failed update.
    with pytest.raises(MusicCastConnectionException):
        await device.fetch()

    device.device.request_json = AsyncMock(return_value=ERROR_RESPONSE)
    with pytest.raises(MusicCastResponseException):
        await device.fetch()

    # The successful network status read stays cached; the failed device info read is asked again.
    assert device.data.network_name == "Living"
    device.device.request_json.assert_awaited_once_with(System.get_device_info())


async def test_failed_name_text_keeps_previous_names(device: MusicCastDevice) -> None:
    device._network_status = {"response_code": 0}
    device._device_info = {"response_code": 0}
    device._features = {"system": {}}
    device._name_text = {"response_code": 0, "input_list": [{"id": "hdmi1", "text": "TV"}]}

    async def respond(url: str) -> dict[str, object]:
        return ERROR_RESPONSE if url == System.get_name_text(None) else {"response_code": 0}

    device.device.request_json = AsyncMock(side_effect=respond)

    await device.fetch()

    assert device.data.input_names == {"hdmi1": "TV"}
