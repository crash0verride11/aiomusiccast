"""Tests for the commands MusicCastDevice sends."""

from datetime import time
from typing import Any

import pytest

from aiomusiccast_co.exceptions import MusicCastException, MusicCastUnsupportedException
from aiomusiccast_co.features import DeviceFeature, ZoneFeature
from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.pyamaha import NetUSB, System, Tuner, Zone

from .common import BASE, FakeYxc

# (method, args, expected write, feature the method requires)
COMMANDS: list[tuple[str, tuple[Any, ...], str | tuple[str, Any], DeviceFeature | ZoneFeature | None]] = [
    ("turn_on", ("main",), Zone.set_power("main", "on"), None),
    ("turn_off", ("zone2",), Zone.set_power("zone2", "standby"), None),
    ("mute_volume", ("main", True), Zone.set_mute("main", True), None),
    ("set_volume_db", ("main", -40.0), Zone.set_volume("main", 81, 1), ZoneFeature.ACTUAL_VOLUME),
    ("set_volume_level", ("main", 0.25), Zone.set_volume("main", 40, 1), None),
    ("set_volume_level", ("main", 1.0), Zone.set_volume("main", 161, 1), None),
    ("volume_up", ("main",), Zone.set_volume("main", "up", None), None),
    ("volume_down", ("main", 5), Zone.set_volume("main", "down", 5), None),
    (
        "set_tone_control",
        ("main", "manual", 2, -2),
        Zone.set_tone_control("main", "manual", 2, -2),
        ZoneFeature.TONE_CONTROL,
    ),
    (
        "set_equalizer",
        ("main", "manual", 1, 2, 3),
        Zone.set_equalizer("main", "manual", 1, 2, 3),
        ZoneFeature.EQUALIZER,
    ),
    ("set_dialogue_level", ("main", 2), Zone.set_dialogue_level("main", 2), ZoneFeature.DIALOGUE_LEVEL),
    ("set_dialogue_lift", ("main", 1), Zone.set_dialogue_lift("main", 1), ZoneFeature.DIALOGUE_LIFT),
    (
        "set_dts_dialogue_control",
        ("main", 3),
        Zone.set_dts_dialogue_control("main", 3),
        ZoneFeature.DTS_DIALOGUE_CONTROL,
    ),
    ("set_extra_bass", ("main", True), Zone.set_extra_bass("main", True), ZoneFeature.EXTRA_BASS),
    ("set_bass_extension", ("main", True), Zone.set_bass_extension("main", True), ZoneFeature.BASS_EXTENSION),
    ("set_enhancer", ("main", False), Zone.set_enhancer("main", False), ZoneFeature.ENHANCER),
    ("set_party_mode", (True,), System.set_partymode(True), DeviceFeature.PARTY_MODE),
    ("set_adaptive_drc", ("main", True), Zone.set_adaptive_drc("main", True), ZoneFeature.ADAPTIVE_DRC),
    ("set_pure_direct", ("main", True), Zone.set_pure_direct("main", True), ZoneFeature.PURE_DIRECT),
    (
        "set_link_audio_delay",
        ("main", "lip_sync"),
        Zone.set_link_audio_delay("main", "lip_sync"),
        ZoneFeature.LINK_AUDIO_DELAY,
    ),
    (
        "set_link_audio_quality",
        ("main", "compressed"),
        Zone.set_link_audio_quality("main", "compressed"),
        ZoneFeature.LINK_AUDIO_QUALITY,
    ),
    ("set_link_control", ("main", "speed"), Zone.set_link_control("main", "speed"), ZoneFeature.LINK_CONTROL),
    (
        "set_surround_decoder",
        ("main", "auto"),
        Zone.set_surr_decoder_type("main", "auto"),
        ZoneFeature.SURR_DECODER_TYPE,
    ),
    ("set_dimmer", (3,), System.set_dimmer(3), DeviceFeature.DIMMER),
    ("set_speaker_a", (False,), System.set_speaker_a(False), DeviceFeature.SPEAKER_A),
    ("set_speaker_b", (True,), System.set_speaker_b(True), DeviceFeature.SPEAKER_B),
    ("set_speaker_pattern", (2,), System.set_speaker_pattern(2), DeviceFeature.SPEAKER_PATTERN),
    ("set_subwoofer_volume", ("main", -3), Zone.set_subwoofer_volume("main", -3), ZoneFeature.SUBWOOFER_VOLUME),
    ("set_clear_voice", ("main", True), Zone.set_clear_voice("main", True), ZoneFeature.CLEAR_VOICE),
    ("set_surround_3d", ("main", True), Zone.set_surround_3d("main", True), ZoneFeature.SURROUND_3D),
    ("set_surround_ai", ("main", False), Zone.set_surround_ai("main", False), ZoneFeature.SURROUND_AI),
    ("select_sound_mode", ("main", "straight"), Zone.set_sound_program("main", "straight"), None),
    ("select_source", ("main", "hdmi2"), Zone.set_input("main", "hdmi2", ""), None),
    ("recall_netusb_preset", ("main", 3), NetUSB.recall_preset("main", 3), None),
    ("store_netusb_preset", (3,), NetUSB.store_preset(3), None),
    ("recall_scene", ("zone2", 2), Zone.recall_scene("zone2", 2), ZoneFeature.SCENE),
    (
        "set_scene_info",
        ("main", 2, "Party"),
        (f"{BASE}/main/setSceneInfo", {"num": 2, "text": "Party"}),
        ZoneFeature.SCENE,
    ),
    ("set_sleep_timer", ("main", 45), Zone.set_sleep("main", 60), None),
    ("set_sleep_timer", ("main",), Zone.set_sleep("main", 0), None),
    ("netusb_play", (), NetUSB.set_playback("play"), None),
    ("netusb_pause", (), NetUSB.set_playback("pause"), None),
    ("netusb_stop", (), NetUSB.set_playback("stop"), None),
    ("netusb_previous_track", (), NetUSB.set_playback("previous"), None),
    ("netusb_next_track", (), NetUSB.set_playback("next"), None),
    ("select_list_item", ("3", "main"), NetUSB.set_list_control("main", "select", "3", "main"), None),
    ("return_in_list", ("main",), NetUSB.set_list_control("main", "return", "", "main"), None),
    ("play_list_media", ("3", "main"), NetUSB.set_list_control("main", "play", "3", "main"), None),
    ("search_list_item", ("Miles", 2), NetUSB.set_search_string("Miles", "main", 2), None),
]


@pytest.mark.parametrize(("method", "args", "expected"), [command[:3] for command in COMMANDS])
async def test_command_sends_request(
    full_device: MusicCastDevice, yxc: FakeYxc, method: str, args: tuple[Any, ...], expected: Any
) -> None:
    await getattr(full_device, method)(*args)

    assert yxc.writes == [expected]


@pytest.mark.parametrize(
    ("method", "args", "feature"),
    [(method, args, feature) for method, args, _, feature in COMMANDS if feature is not None],
)
async def test_command_requires_feature(
    full_device: MusicCastDevice, yxc: FakeYxc, method: str, args: tuple[Any, ...], feature: DeviceFeature | ZoneFeature
) -> None:
    if isinstance(feature, ZoneFeature):
        full_device.data.zones[args[0]].features &= ~feature
    else:
        full_device.features &= ~feature

    with pytest.raises(MusicCastUnsupportedException):
        await getattr(full_device, method)(*args)
    assert yxc.writes == []


async def test_zone_command_for_missing_zone_raises(device: MusicCastDevice, yxc: FakeYxc) -> None:
    with pytest.raises(MusicCastException):
        await device.set_surround_ai("zone3", True)
    assert yxc.writes == []


async def test_dimmer_value_out_of_range_raises(full_device: MusicCastDevice, yxc: FakeYxc) -> None:
    with pytest.raises(MusicCastException):
        await full_device.set_dimmer(16)
    assert yxc.writes == []


# -- playback modes -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("shuffle", "expected"), [(True, "on"), (False, "off")])
async def test_netusb_shuffle(device: MusicCastDevice, yxc: FakeYxc, shuffle: bool, expected: str) -> None:
    await device.netusb_shuffle(shuffle)

    assert yxc.writes == [NetUSB.set_shuffle(expected)]


@pytest.mark.parametrize(
    ("current", "shuffle", "toggles"), [("off", True, True), ("on", True, False), ("on", False, True)]
)
async def test_netusb_shuffle_on_old_api_toggles(
    device: MusicCastDevice, yxc: FakeYxc, current: str, shuffle: bool, toggles: bool
) -> None:
    device.data.api_version = 1.17
    device.data.netusb_shuffle = current

    await device.netusb_shuffle(shuffle)

    assert yxc.writes == ([NetUSB.toggle_shuffle()] if toggles else [])


async def test_netusb_repeat(device: MusicCastDevice, yxc: FakeYxc) -> None:
    await device.netusb_repeat("all")

    assert yxc.writes == [NetUSB.set_repeat("all")]


@pytest.mark.parametrize(("current", "toggles"), [("off", True), ("all", False)])
async def test_netusb_repeat_on_old_api_toggles(
    device: MusicCastDevice, yxc: FakeYxc, current: str, toggles: bool
) -> None:
    device.data.api_version = 1.17
    device.data.netusb_repeat = current

    await device.netusb_repeat("all")

    assert yxc.writes == ([NetUSB.toggle_repeat()] if toggles else [])


@pytest.mark.parametrize(
    ("band", "previous", "following"),
    [
        ("fm", Tuner.set_freq("fm", "auto_down", 0), Tuner.set_freq("fm", "auto_up", 0)),
        ("am", Tuner.set_freq("am", "auto_down", 0), Tuner.set_freq("am", "auto_up", 0)),
        ("dab", Tuner.set_dab_service("previous"), Tuner.set_dab_service("next")),
    ],
)
async def test_tuner_station_steps(
    device: MusicCastDevice, yxc: FakeYxc, band: str, previous: str, following: str
) -> None:
    device.data.band = band

    await device.tuner_previous_station()
    await device.tuner_next_station()

    assert yxc.writes == [previous, following]


async def test_tuner_station_steps_without_band(device: MusicCastDevice, yxc: FakeYxc) -> None:
    device.data.band = None

    await device.tuner_previous_station()
    await device.tuner_next_station()

    assert yxc.writes == []


# -- alarm ----------------------------------------------------------------------------------------------------------

ALARM_URL = f"{BASE}/clock/setAlarmSettings"


async def test_configure_alarm_switch_and_volume(full_device: MusicCastDevice, yxc: FakeYxc) -> None:
    # alarm_volume range is 0..60 in steps of 2
    await full_device.configure_alarm(alarm_on=False, volume=0.5)

    assert yxc.writes == [(ALARM_URL, {"alarm_on": False, "volume": 30})]


async def test_configure_alarm_resume_day(full_device: MusicCastDevice, yxc: FakeYxc) -> None:
    await full_device.configure_alarm(
        mode="weekly", day="monday", alarm_time="06:45", source="resume:tuner", enable_day=True, beep=False
    )

    detail = {
        "day": "monday",
        "enable": True,
        "time": "0645",
        "beep": False,
        "playback_type": "resume",
        "resume": {"input": "tuner"},
    }
    assert yxc.writes == [(ALARM_URL, {"mode": "weekly", "detail": detail})]


async def test_configure_alarm_preset_with_time_object(full_device: MusicCastDevice, yxc: FakeYxc) -> None:
    await full_device.configure_alarm(mode="weekly", day="tuesday", alarm_time=time(7, 5), source="preset:netusb:2")

    detail = {"day": "tuesday", "time": "0705", "playback_type": "preset", "preset": {"num": 2, "type": "netusb"}}
    assert yxc.writes == [(ALARM_URL, {"mode": "weekly", "detail": detail})]


async def test_configure_alarm_sends_stored_time_with_day(full_device: MusicCastDevice, yxc: FakeYxc) -> None:
    # The device only applies beep together with a time or source, so the stored time is always sent along.
    await full_device.configure_alarm(mode="weekly", day="monday", beep=False)

    assert yxc.writes == [(ALARM_URL, {"mode": "weekly", "detail": {"day": "monday", "time": "0700", "beep": False}})]


@pytest.mark.parametrize(
    "kwargs",
    [{"day": "monday"}, {"mode": "weekly"}, {"source": "resume:tuner"}, {"alarm_time": "07:00"}, {"beep": True}],
)
async def test_configure_alarm_day_settings_need_mode_and_day(
    full_device: MusicCastDevice, yxc: FakeYxc, kwargs: dict[str, Any]
) -> None:
    with pytest.raises(AssertionError):
        await full_device.configure_alarm(**kwargs)
    assert yxc.writes == []


# -- list browsing and URL playback --------------------------------------------------------------------------------


async def test_get_list_info(device: MusicCastDevice, yxc: FakeYxc) -> None:
    info = await device.get_list_info("net_radio", 0)

    assert info["menu_name"] == "NET RADIO"
    assert yxc.reads == [NetUSB.get_list_info("net_radio", 0, 8, "en", "main")]


@pytest.mark.parametrize(
    ("url", "mime_type", "expected_mime", "upnp_class"),
    [
        ("http://192.0.2.9/song.mp3", None, "audio/mpeg", "object.item.audioItem"),
        (
            "http://192.0.2.9/live",
            "application/vnd.apple.mpegurl",
            "application/vnd.apple.mpegurl",
            "object.item.videoItem",
        ),
        ("http://192.0.2.9/photo.jpg", None, "image/jpeg", "object.item.imageItem"),
        ("http://192.0.2.9/stream", None, "application/octet-stream", "object.item"),
    ],
)
async def test_play_url_media(
    device: MusicCastDevice, yxc: FakeYxc, url: str, mime_type: str | None, expected_mime: str, upnp_class: str
) -> None:
    await device.play_url_media("main", url, "Title", mime_type)

    assert yxc.writes == [Zone.set_input("main", "server", "autoplay_disabled")]
    actions = [call.args[0] for call in yxc.dlna.await_args_list]
    assert actions == ["Stop", "SetAVTransportURI", "Play"]

    transport = yxc.dlna.await_args_list[1].args[1]
    assert transport["CurrentURI"] == url
    metadata = transport["CurrentURIMetaData"]
    # The DIDL-Lite metadata is XML-escaped once more to travel inside the SOAP body.
    assert f"&lt;upnp:class&gt;{upnp_class}&lt;/upnp:class&gt;" in metadata
    assert f"http-get:*:{expected_mime}:*" in metadata
    assert "&lt;dc:title&gt;Title&lt;/dc:title&gt;" in metadata
