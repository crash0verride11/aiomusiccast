"""Tests for building capabilities from device data."""

from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from aiomusiccast_co.capabilities import Capability, NumberSetter, OptionSetter, Scene, StatefulCapability
from aiomusiccast_co.capability_registry import build_zone_capabilities, normalize_option
from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.pyamaha import System, Zone

from .common import FakeYxc


def describe(capability: Capability) -> dict[str, Any]:
    """Return the snapshot-relevant attributes of a capability."""
    result: dict[str, Any] = {
        "type": type(capability).__name__,
        "name": capability.name,
        "entity_type": capability.entity_type.name,
    }
    if isinstance(capability, StatefulCapability):
        result["current"] = capability.current
    if isinstance(capability, NumberSetter):
        result["range"] = (capability.value_range.minimum, capability.value_range.maximum, capability.value_range.step)
        result["unit"] = capability.unit
    if isinstance(capability, OptionSetter):
        result["options"] = dict(capability.options)
    return result


def describe_all(device: MusicCastDevice) -> dict[str, dict[str, Any]]:
    device.build_capabilities()
    return {
        "device": {cap.id: describe(cap) for cap in device.data.capabilities},
        **{
            zone_id: {cap.id: describe(cap) for cap in zone.capabilities} for zone_id, zone in device.data.zones.items()
        },
    }


def scenes(device: MusicCastDevice, zone_id: str = "main") -> dict[int, Scene]:
    return {
        int(cap.id.rsplit("_", 1)[1]): cap for cap in build_zone_capabilities(device, zone_id) if isinstance(cap, Scene)
    }


def test_rx_a4a_capabilities(device: MusicCastDevice, snapshot: SnapshotAssertion) -> None:
    assert describe_all(device) == snapshot


def test_capabilities_of_features_missing_on_rx_a4a(full_device: MusicCastDevice, snapshot: SnapshotAssertion) -> None:
    assert describe_all(full_device) == snapshot


@pytest.mark.parametrize(
    ("zone_id", "capability_id", "value", "expected"),
    [
        (None, "DIMMER", -1, System.set_dimmer(-1)),
        (None, "SPEAKER_A", False, System.set_speaker_a(False)),
        (None, "SPEAKER_B", True, System.set_speaker_b(True)),
        (None, "PARTY_MODE", True, System.set_partymode(True)),
        (None, "SPEAKER_PATTERN", 2, System.set_speaker_pattern(2)),
        ("main", "zone_SURR_DECODER_TYPE", "dts_neural_x", Zone.set_surr_decoder_type("main", "dts_neural_x")),
        ("main", "zone_SLEEP", 60, Zone.set_sleep("main", 60)),
        ("main", "zone_EQUALIZER_mode", "bypass", Zone.set_equalizer("main", "bypass", None, None, None)),
        ("main", "zone_EQUALIZER_low", -2, Zone.set_equalizer("main", None, -2, None, None)),
        ("main", "zone_EQUALIZER_mid", 3, Zone.set_equalizer("main", None, None, 3, None)),
        ("main", "zone_EQUALIZER_high", 10, Zone.set_equalizer("main", None, None, None, 10)),
        ("main", "zone_TONE_CONTROL_mode", "manual", Zone.set_tone_control("main", "manual", None, None)),
        ("main", "zone_TONE_CONTROL_bass", -6, Zone.set_tone_control("main", None, -6, None)),
        ("main", "zone_TONE_CONTROL_treble", 6, Zone.set_tone_control("main", None, None, 6)),
        ("main", "zone_DIALOGUE_LEVEL", 2, Zone.set_dialogue_level("main", 2)),
        ("main", "zone_DIALOGUE_LIFT", 1, Zone.set_dialogue_lift("main", 1)),
        ("main", "zone_DTS_DIALOGUE_CONTROL", 3, Zone.set_dts_dialogue_control("main", 3)),
        ("main", "zone_LINK_AUDIO_DELAY", "lip_sync", Zone.set_link_audio_delay("main", "lip_sync")),
        ("main", "zone_LINK_CONTROL", "speed", Zone.set_link_control("main", "speed")),
        ("main", "zone_LINK_AUDIO_QUALITY", "compressed", Zone.set_link_audio_quality("main", "compressed")),
        ("main", "zone_BASS_EXTENSION", False, Zone.set_bass_extension("main", False)),
        ("main", "zone_EXTRA_BASS", True, Zone.set_extra_bass("main", True)),
        ("main", "zone_ENHANCER", True, Zone.set_enhancer("main", True)),
        ("main", "zone_PURE_DIRECT", True, Zone.set_pure_direct("main", True)),
        ("main", "zone_ADAPTIVE_DRC", True, Zone.set_adaptive_drc("main", True)),
        ("main", "zone_ACTUAL_VOLUME", -30.0, Zone.set_volume("main", 101, 1)),
        ("main", "zone_SUBWOOFER_VOLUME", -4, Zone.set_subwoofer_volume("main", -4)),
        ("main", "zone_CLEAR_VOICE", True, Zone.set_clear_voice("main", True)),
        ("main", "zone_SURROUND_3D", False, Zone.set_surround_3d("main", False)),
        ("main", "zone_SURROUND_AI", False, Zone.set_surround_ai("main", False)),
    ],
)
async def test_setting_a_capability_sends_its_request(
    full_device: MusicCastDevice, yxc: FakeYxc, zone_id: str | None, capability_id: str, value: Any, expected: str
) -> None:
    full_device.build_capabilities()
    capabilities = full_device.data.zones[zone_id].capabilities if zone_id else full_device.data.capabilities
    capability = next(cap for cap in capabilities if cap.id == capability_id)

    await capability.set(value)

    assert yxc.writes == [expected]


async def test_actual_volume_needs_a_db_range(device: MusicCastDevice) -> None:
    del device.data.zones["main"].range_step["actual_volume_db"]

    ids = [cap.id for cap in build_zone_capabilities(device, "main")]

    assert "zone_ACTUAL_VOLUME" not in ids
    assert "zone_SURROUND_AI" in ids


async def test_scene_activate_recalls_its_own_number(device: MusicCastDevice, yxc: FakeYxc) -> None:
    # A late-binding lambda in the registry would make every scene recall the last one (8).
    await scenes(device)[1].activate()

    assert yxc.writes == [Zone.recall_scene("main", 1)]


async def test_scene_names_follow_refetched_scene_info(device: MusicCastDevice, yxc: FakeYxc) -> None:
    main_scenes = scenes(device)
    scene_list = [{"num": 1, "text": "Movie Night"}, {"num": 2, "text": "Radio Listening"}]
    yxc.set("main/getSceneInfo", {"response_code": 0, "scene_list": scene_list})

    await device._fetch_scenes("main")

    assert (main_scenes[1].name, main_scenes[2].name) == ("1: Movie Night", "2: Radio Listening")


async def test_failed_scene_fetch_keeps_previous_names(device: MusicCastDevice, yxc: FakeYxc) -> None:
    main_scenes = scenes(device)
    yxc.fail("main/getSceneInfo")

    await device._fetch_scenes("main")

    assert main_scenes[1].name == "1: SCENE1"
    assert device.data.zones["main"].scene_information[8] == "SCENE8"


@pytest.mark.parametrize("scene_information", [{}, None])
async def test_scene_name_falls_back_for_unknown_number(
    device: MusicCastDevice, scene_information: dict[int, str] | None
) -> None:
    main_scenes = scenes(device)

    device.data.zones["main"].scene_information = scene_information

    assert main_scenes[3].name == "3: Scene 3"


@pytest.mark.parametrize(("option", "expected"), [("Dolby Surround", "dolby_surround"), (-1, "-1"), ("auto", "auto")])
def test_normalize_option(option: object, expected: str) -> None:
    assert normalize_option(option) == expected
