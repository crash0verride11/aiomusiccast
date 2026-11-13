"""Tests for the YXC URL builders in pyamaha."""

import pytest

from aiomusiccast_co.exceptions import MusicCastParamException
from aiomusiccast_co.pyamaha import Clock, Dist, NetUSB, System, Tuner, UrlBuilder, Zone

from .common import BASE


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (Zone.get_status("zone2"), f"{BASE}/zone2/getStatus"),
        (Zone.set_power("main", "on"), f"{BASE}/main/setPower?power=on"),
        (Zone.set_mute("main", True), f"{BASE}/main/setMute?enable=true"),
        (Zone.set_volume("main", 81, None), f"{BASE}/main/setVolume?volume=81"),
        (Zone.set_volume("main", "up", 5), f"{BASE}/main/setVolume?volume=up&step=5"),
        (
            Zone.set_input("main", "server", "autoplay_disabled"),
            f"{BASE}/main/setInput?input=server&mode=autoplay_disabled",
        ),
        (Zone.set_tone_control("main", None, 2, None), f"{BASE}/main/setToneControl?bass=2"),
        (Zone.set_equalizer("main", "manual", -1, 0, 1), f"{BASE}/main/setEqualizer?mode=manual&low=-1&mid=0&high=1"),
        (Zone.set_surround_ai("main", True), f"{BASE}/main/setSurroundAI?enable=true"),
        (Zone.set_surround_ai("zone2", False), f"{BASE}/zone2/setSurroundAI?enable=false"),
        (Zone.set_dts_dialogue_control("main", 3), f"{BASE}/main/setDtsDialogueControl?num=3"),
        (Zone.set_surr_decoder_type("main", "auto"), f"{BASE}/main/setSurroundDecoderType?type=auto"),
        (Zone.recall_scene("main", 3), f"{BASE}/main/recallScene?num=3"),
        (Zone.get_scene_info("main"), f"{BASE}/main/getSceneInfo"),
        (Zone.get_scene_info("main", 2), f"{BASE}/main/getSceneInfo?num=2"),
        (System.set_speaker_a(True), f"{BASE}/system/setSpeakerA?enable=true"),
        (System.set_partymode(False), f"{BASE}/system/setPartyMode?enable=false"),
        (Tuner.set_freq("fm", "auto_up", 0), f"{BASE}/tuner/setFreq?band=fm&tuning=auto_up&num=0"),
        (Tuner.set_dab_service("next"), f"{BASE}/tuner/setDabService?dir=next"),
        (NetUSB.set_repeat("all"), f"{BASE}/netusb/setRepeat?mode=all"),
        (NetUSB.recall_preset("main", 3), f"{BASE}/netusb/recallPreset?zone=main&num=3"),
        (
            NetUSB.get_list_info("usb", 8, 8, "en", "main"),
            f"{BASE}/netusb/getListInfo?input=usb&index=8&size=8&lang=en&list_id=main",
        ),
        (
            NetUSB.set_list_control("main", "select", 3, "zone2"),
            f"{BASE}/netusb/setListControl?list_id=main&type=select&index=3&zone=zone2",
        ),
        (Dist.start_distribution(1), f"{BASE}/dist/startDistribution?num=1"),
    ],
)
def test_get_urls(url: str, expected: str) -> None:
    assert url == expected


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (Zone.set_scene_info("main", 2, "Party"), (f"{BASE}/main/setSceneInfo", {"num": 2, "text": "Party"})),
        (Dist.set_server_info(""), (f"{BASE}/dist/setServerInfo", {"group_id": ""})),
        (
            Dist.set_server_info("g", "main", "add", ["192.0.2.2"]),
            (
                f"{BASE}/dist/setServerInfo",
                {"group_id": "g", "zone": "main", "type": "add", "client_list": ["192.0.2.2"]},
            ),
        ),
        (
            Dist.set_client_info("g", ["main"], "192.0.2.10"),
            (f"{BASE}/dist/setClientInfo", {"group_id": "g", "zone": ["main"], "server_ip_address": "192.0.2.10"}),
        ),
        (Dist.set_group_name("Party"), (f"{BASE}/dist/setGroupName", {"name": "Party"})),
        (
            Clock.set_alarm_settings(mode="oneday", day="oneday", repeat=True, enable=True),
            (
                f"{BASE}/clock/setAlarmSettings",
                {"mode": "oneday", "repeat": True, "detail": {"day": "oneday", "enable": True}},
            ),
        ),
    ],
)
def test_post_requests(request_: tuple[str, dict], expected: tuple[str, dict]) -> None:
    assert request_ == expected


def test_scene_number_is_sent_as_json_integer() -> None:
    # setSceneInfo rejects a string num; see the set_scene_info note in CLAUDE.md.
    _, body = Zone.set_scene_info("main", 2, "Party")

    assert isinstance(body["num"], int)


def test_query_drops_unset_optional_params() -> None:
    assert UrlBuilder.build_query_str({"a": False, "b": False}, a=1, b=None) == "a=1"


def test_query_rejects_unknown_params() -> None:
    with pytest.raises(MusicCastParamException, match="Unknown parameter"):
        UrlBuilder.build_query_str({"a": False}, b=1)


def test_query_requires_required_params() -> None:
    with pytest.raises(MusicCastParamException, match="required"):
        UrlBuilder.build_query_str({"num": True}, num=None)


def test_zone_url_rejects_unknown_zone() -> None:
    with pytest.raises(AssertionError, match="Invalid ZONE"):
        Zone.recall_scene("zone9", 1)


def test_list_info_rejects_unknown_language() -> None:
    with pytest.raises(AssertionError, match="Invalid LANG"):
        NetUSB.get_list_info("usb", 0, 8, "xx", "main")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"day": "monday", "repeat": True},
        {"day": "monday", "playback_type": "resume", "preset_num": 1},
        {"day": "monday", "playback_type": "preset", "resume_input": "tuner"},
        {"day": "someday"},
        {"volume": 0.5},
    ],
)
def test_alarm_settings_reject_invalid_combinations(kwargs: dict) -> None:
    with pytest.raises(AssertionError):
        Clock.set_alarm_settings(**kwargs)
