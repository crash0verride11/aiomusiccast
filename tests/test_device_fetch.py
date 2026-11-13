"""Tests for reading device state with MusicCastDevice.fetch()."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from syrupy.assertion import SnapshotAssertion

from aiomusiccast_co.exceptions import MusicCastConnectionException, MusicCastResponseException
from aiomusiccast_co.features import DeviceFeature, ZoneFeature
from aiomusiccast_co.musiccast_data import Category
from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.pyamaha import System

from .common import FakeYxc, create_device

VOLATILE = {"group_update_lock", "netusb_play_time_updated", "capabilities", "zones"}


def data_snapshot(device: MusicCastDevice) -> dict[str, Any]:
    """Return the device data as plain values, leaving out locks, timestamps and capabilities."""
    data = {key: value for key, value in vars(device.data).items() if key not in VOLATILE}
    data["features"] = sorted(str(feature.name) for feature in device.features)
    data["zones"] = {
        zone_id: {
            **{k: v for k, v in vars(zone).items() if k not in {"capabilities", "features"}},
            "features": sorted(str(feature.name) for feature in zone.features),
        }
        for zone_id, zone in device.data.zones.items()
    }
    return data


def test_rx_a4a_data(device: MusicCastDevice, snapshot: SnapshotAssertion) -> None:
    assert data_snapshot(device) == snapshot


def test_rx_a4a_basics(device: MusicCastDevice) -> None:
    data = device.data
    assert (data.model_name, data.category, data.network_name) == ("RX-A4A", Category.AV_RECEIVER, "Yamaha RX-A4A")
    assert list(data.zones) == ["main", "zone2"]
    assert (data.zones["main"].name, data.zones["zone2"].name) == ("Main", "Zone2")
    assert data.input_names["net_radio"] == "NET RADIO"
    assert ZoneFeature.SURROUND_AI in data.zones["main"].features
    assert ZoneFeature.SURROUND_AI not in data.zones["zone2"].features
    assert DeviceFeature.SPEAKER_PATTERN in device.features
    assert DeviceFeature.CLOCK not in device.features


async def test_setup_reads_are_cached(device: MusicCastDevice, yxc: FakeYxc) -> None:
    await device.fetch()

    for path in ("system/getNetworkStatus", "system/getDeviceInfo", "system/getFeatures"):
        assert yxc.read_count(path) == 0
    for path in ("system/getNameText", "main/getStatus", "zone2/getStatus", "dist/getDistributionInfo"):
        assert yxc.read_count(path) == 1


async def test_renamed_input_is_picked_up_on_next_fetch(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.update("system/getNameText", input_list=[{"id": "hdmi1", "text": "Apple TV"}])

    await device.fetch()

    assert device.data.input_names == {"hdmi1": "Apple TV"}


async def test_unknown_func_list_entries_are_logged(yxc: FakeYxc, caplog: pytest.LogCaptureFixture) -> None:
    features = yxc.responses["system/getFeatures"]
    assert isinstance(features, dict)
    features["system"]["func_list"].append("teleport")
    features["zone"][0]["func_list"].append("levitate")

    with caplog.at_level(logging.INFO):
        await create_device(yxc)

    assert "supports the feature teleport" in caplog.text
    assert "Zone main of model RX-A4A supports the feature levitate" in caplog.text


async def test_optional_sources_are_skipped_when_absent(yxc: FakeYxc) -> None:
    features = yxc.responses["system/getFeatures"]
    assert isinstance(features, dict)
    del features["tuner"]
    features["netusb"]["func_list"] = []

    await create_device(yxc)

    assert yxc.read_count("tuner/getPlayInfo") == 0
    assert yxc.read_count("netusb/getPlayInfo") == 0


async def test_zone_volume_without_db_mode_has_no_actual_volume(yxc: FakeYxc) -> None:
    yxc.update("zone2/getStatus", actual_volume={"mode": "numeric", "value": 40.5, "unit": ""})

    device = await create_device(yxc)

    assert device.data.zones["zone2"].actual_volume is None


# -- features the RX-A4A lacks ------------------------------------------------------------------------------------


def test_clock_and_alarm_features(full_device: MusicCastDevice) -> None:
    data = full_device.data
    assert {DeviceFeature.CLOCK, DeviceFeature.ALARM_ONEDAY, DeviceFeature.ALARM_WEEKLY} <= set(full_device.features)
    assert (data.alarm_volume_range, data.alarm_volume_step) == ((0, 60), 2)
    assert (data.alarm_fade_range, data.alarm_fade_step) == ((1, 30), 1)
    assert data.alarm_preset_list == ["netusb", "tuner"]
    assert data.alarm_resume_input_list == ["tuner", "audio1"]


def test_alarm_settings(full_device: MusicCastDevice) -> None:
    data = full_device.data
    assert (data.alarm_on, data.alarm_volume, data.alarm_mode) == (True, 30, "weekly")
    assert set(data.alarm_details) == {
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "oneday",
    }

    monday = data.alarm_details["monday"]
    assert (monday.enabled, monday.time, monday.beep, monday.input) == (True, "07:00", True, "preset:netusb:2")
    assert monday.preset_info == {"input": "net_radio", "text": "Jazz"}
    assert data.alarm_details["tuesday"].preset_info == {"band": "fm", "number": 98100}
    assert data.alarm_details["oneday"].input == "resume:tuner"
    assert data.alarm_details["sunday"].time is None


def test_dimmer_and_speakers(full_device: MusicCastDevice) -> None:
    data = full_device.data
    assert data.dimmer is not None
    assert (data.dimmer.minimum, data.dimmer.maximum, data.dimmer.dimmer_current) == (-1, 15, 5)
    assert (data.speaker_a, data.speaker_b) == (True, False)


def test_soundbar_zone_fields(full_device: MusicCastDevice) -> None:
    main = full_device.data.zones["main"]
    assert (main.equalizer_mode, main.equalizer_low, main.equalizer_mid, main.equalizer_high) == ("manual", 0, 1, -1)
    assert (main.clear_voice, main.surround_3d, main.bass_extension) == (False, True, True)
    assert main.link_audio_quality == "uncompressed"


# -- derived state --------------------------------------------------------------------------------------------------


async def test_netusb_play_info(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.update(
        "netusb/getPlayInfo",
        input="net_radio",
        playback="play",
        artist="Artist",
        album="Album",
        track="Track",
        albumart_url="/YamahaRemoteControl/AlbumART/AlbumART8546.jpg",
        play_time=12,
        total_time=200,
    )

    await device._fetch_netusb()

    data = device.data
    assert (data.netusb_input, data.netusb_playback, data.netusb_track) == ("net_radio", "play", "Track")
    assert (data.netusb_play_time, data.netusb_total_time) == (12, 200)
    assert data.netusb_play_time_updated is not None
    assert device.media_image_url == "http://192.0.2.1/YamahaRemoteControl/AlbumART/AlbumART8546.jpg"


def test_media_image_url_is_empty_without_album_art(device: MusicCastDevice) -> None:
    assert device.media_image_url == ""


async def test_netusb_presets_skip_empty_slots(device: MusicCastDevice, yxc: FakeYxc) -> None:
    presets = [{"input": "unknown", "text": ""}] * 3
    presets[1] = {"input": "net_radio", "text": "Jazz FM"}
    yxc.set("netusb/getPresetInfo", {"response_code": 0, "preset_info": presets})

    await device._fetch_netusb_presets()

    assert device.data.netusb_preset_list == {2: ("net_radio", "Jazz FM")}


@pytest.mark.parametrize(
    ("play_info", "title", "artist"),
    [
        ({"band": "fm"}, None, "FM 98.10 MHz"),
        ({"band": "am", "am": {"freq": 1080}}, None, "AM 1080.00 KHz"),
        ({"band": "fm", "rds": {"radio_text_a": " News ", "radio_text_b": ""}}, "News", "FM 98.10 MHz"),
        ({"band": "fm", "rds": {"radio_text_a": "", "radio_text_b": "Song"}}, "Song", "FM 98.10 MHz"),
        ({"band": "fm", "rds": {"radio_text_a": "News", "radio_text_b": "Song"}}, "News / Song", "FM 98.10 MHz"),
        ({"band": "dab", "dab": {"service_label": " BBC 6 ", "dls": " Now playing "}}, "Now playing", "BBC 6"),
    ],
)
async def test_tuner_media_info(
    device: MusicCastDevice, yxc: FakeYxc, play_info: dict[str, Any], title: str | None, artist: str
) -> None:
    yxc.update("tuner/getPlayInfo", **play_info)

    await device._fetch_tuner()

    assert (device.tuner_media_title, device.tuner_media_artist) == (title, artist)


def test_tuner_media_artist_without_band(device: MusicCastDevice) -> None:
    device.data.band = None

    assert device.tuner_media_artist is None


async def test_alarm_input_list(full_device: MusicCastDevice) -> None:
    full_device.data.netusb_preset_list = {2: ("net_radio", "Jazz FM")}

    assert full_device.alarm_input_list == {
        "resume:tuner": "Resume TUNER",
        "resume:audio1": "Resume AUDIO1",
        "preset:netusb:2": "NET RADIO - Jazz FM",
    }


def test_alarm_input_list_without_netusb_presets(device: MusicCastDevice) -> None:
    device.data.alarm_resume_input_list = ["tuner"]

    assert device.alarm_input_list == {"resume:tuner": "Resume TUNER"}


def test_save_inputs_exclude_link_sources(device: MusicCastDevice) -> None:
    save_inputs = device.get_save_inputs("main")

    assert "hdmi1" in save_inputs
    assert "net_radio" in save_inputs
    assert not {"mc_link", "main_sync"} & set(save_inputs)


def test_save_inputs_exclude_netusb_sources_in_use(device: MusicCastDevice) -> None:
    device.data.netusb_input = "spotify"
    device.data.zones["zone2"].input = "spotify"

    save_inputs = device.get_save_inputs("main")

    assert "hdmi1" in save_inputs
    assert not {"spotify", "net_radio", "server"} & set(save_inputs)


def test_save_inputs_of_unknown_zone(device: MusicCastDevice) -> None:
    assert device.get_save_inputs("zone3") == []


# -- error responses ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "attr", "value"),
    [
        ("_fetch_netusb", "netusb/getPlayInfo", "netusb_total_time", 200),
        ("_fetch_netusb_presets", "netusb/getPresetInfo", "netusb_preset_list", {1: ("spotify", "Morning")}),
        ("_fetch_tuner", "tuner/getPlayInfo", "band", "am"),
        ("_fetch_distribution_data", "dist/getDistributionInfo", "group_id", "abc123"),
        ("_fetch_func_status", "system/getFuncStatus", "speaker_pattern", 2),
    ],
)
async def test_failed_poll_keeps_device_data(
    device: MusicCastDevice, yxc: FakeYxc, method: str, path: str, attr: str, value: object
) -> None:
    setattr(device.data, attr, value)
    group_update = AsyncMock()
    device.register_group_update_callback(group_update)
    yxc.fail(path)

    await getattr(device, method)()

    assert getattr(device.data, attr) == value
    group_update.assert_not_awaited()


async def test_failed_clock_poll_keeps_alarm_data(full_device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.fail("clock/getSettings")

    await full_device._fetch_clock_data()

    assert full_device.data.alarm_details["monday"].time == "07:00"


async def test_failed_zone_poll_keeps_zone_data(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.fail("main/getStatus")

    await device._fetch_zone("main")

    main = device.data.zones["main"]
    assert (main.power, main.input, main.current_volume, main.surround_ai) == ("standby", "hdmi1", 112, True)


async def test_failed_setup_read_raises_and_is_retried(yxc: FakeYxc) -> None:
    device = MusicCastDevice("192.0.2.1", MagicMock())
    yxc.install(device)
    yxc.fail("system/getDeviceInfo")

    # A subclass of MusicCastConnectionException, so consumers' existing handling turns it into a failed update.
    with pytest.raises(MusicCastConnectionException):
        await device.fetch()
    with pytest.raises(MusicCastResponseException):
        await device.fetch()

    # The successful network status read stays cached; the failed device info read is asked again.
    assert yxc.read_count("system/getNetworkStatus") == 1
    assert yxc.reads.count(System.get_device_info()) == 2
    assert device.data.network_name == "Yamaha RX-A4A"


async def test_failed_name_text_keeps_previous_names(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.fail("system/getNameText")

    await device.fetch()

    assert device.data.input_names["hdmi1"] == "HDMI1"


async def test_failed_first_name_text_read_raises(yxc: FakeYxc) -> None:
    device = MusicCastDevice("192.0.2.1", MagicMock())
    yxc.install(device)
    yxc.fail("system/getNameText")

    with pytest.raises(MusicCastResponseException, match="getNameText"):
        await device.fetch()


# -- discovery helpers ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("<root><yamaha:X_yxcControlURL>/YamahaExtendedControl/v1/</yamaha:X_yxcControlURL></root>", True),
        ("<root><friendlyName>Some TV</friendlyName></root>", False),
    ],
)
async def test_check_yamaha_ssdp(description: str, expected: bool) -> None:
    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(text=AsyncMock(return_value=description)))

    assert await MusicCastDevice.check_yamaha_ssdp("http://192.0.2.1:49154/desc.xml", client) is expected
    client.get.assert_awaited_once_with("http://192.0.2.1:49154/desc.xml")


async def test_get_device_info() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        return_value=MagicMock(text=AsyncMock(return_value='{"response_code": 0, "model_name": "RX-A4A"}'))
    )

    info = await MusicCastDevice.get_device_info("192.0.2.1", client)

    assert info == {"response_code": 0, "model_name": "RX-A4A"}
    assert client.get.await_args.args[0] == "http://192.0.2.1/YamahaExtendedControl/v1/system/getDeviceInfo"
