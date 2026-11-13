"""Tests for the data containers in musiccast_data."""

import pytest

from aiomusiccast_co.exceptions import MusicCastException
from aiomusiccast_co.musiccast_data import Category, Dimmer, MusicCastAlarmDetails, MusicCastData, RangeStep


@pytest.mark.parametrize(("code", "category"), [(1, Category.AV_RECEIVER), (6, Category.DESKTOP_AUDIO_1)])
def test_category_from_code(code: int, category: Category) -> None:
    assert Category(code) is category


def test_unknown_category_code_is_unknown() -> None:
    assert Category(99) is Category.UNKNOWN


@pytest.mark.parametrize("value", [-80.5, -24.5, 0, 16.5])
def test_range_step_accepts_values_on_the_grid(value: float) -> None:
    RangeStep(minimum=-80.5, maximum=16.5, step=0.5).check(value)


@pytest.mark.parametrize("value", [-81, 17, -24.25])
def test_range_step_rejects_values_off_the_grid(value: float) -> None:
    with pytest.raises(MusicCastException):
        RangeStep(minimum=-80.5, maximum=16.5, step=0.5).check(value)


def test_dimmer_is_a_range_with_current_value() -> None:
    dimmer = Dimmer(-1, 15, 1, 7)

    assert (dimmer.minimum, dimmer.maximum, dimmer.step, dimmer.dimmer_current) == (-1, 15, 1, 7)
    dimmer.check(-1)
    with pytest.raises(MusicCastException):
        dimmer.check(16)


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (MusicCastAlarmDetails(playback_type="preset", preset_type="netusb", preset=3), "preset:netusb:3"),
        (MusicCastAlarmDetails(playback_type="resume", resume_input="tuner"), "resume:tuner"),
        (MusicCastAlarmDetails(), None),
    ],
)
def test_alarm_details_input(details: MusicCastAlarmDetails, expected: str | None) -> None:
    assert details.input == expected


def test_tuner_frequency_strings() -> None:
    data = MusicCastData()
    data.fm_freq = 98100
    data.am_freq = 1080

    assert data.fm_freq_str == "FM 98.10 MHz"
    assert data.am_freq_str == "AM 1080.00 KHz"
