"""Tests for the yamaha_musiccast media_player platform.

Covers the device class and icon logic in MusicCastMediaPlayer, which is
driven by the category_code the device reports in its getDeviceInfo response.
The coordinator parses this into a Category enum; the entity maps it to a
MediaPlayerDeviceClass and a matching MDI icon.
"""

from __future__ import annotations

import pytest

from homeassistant.components.media_player import MediaPlayerDeviceClass

from custom_components.yamaha_musiccast.aiomusiccast.musiccast_data import Category
from custom_components.yamaha_musiccast.media_player import (
    MusicCastMediaPlayer,
    _CATEGORY_TO_DEVICE_CLASS,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_player(coordinator) -> MusicCastMediaPlayer:
    return MusicCastMediaPlayer("main", "My Speaker", "entry_id", coordinator)


# ---------------------------------------------------------------------------
# Category enum
# ---------------------------------------------------------------------------


class TestCategoryEnum:

    @pytest.mark.parametrize(
        "code, expected",
        [
            (0, Category.UNKNOWN),
            (1, Category.AV_RECEIVER),
            (2, Category.SOUNDBAR),
            (3, Category.STEREO_RECEIVER),
            (4, Category.SUBWOOFER),
            (5, Category.MINI_SYSTEM),
            (6, Category.DESKTOP_AUDIO_1),
        ],
    )
    def test_known_codes(self, code, expected):
        assert Category(code) == expected

    @pytest.mark.parametrize("code", [99, 255, -1, 1000])
    def test_unknown_codes_fall_back_to_unknown(self, code):
        assert Category(code) == Category.UNKNOWN


# ---------------------------------------------------------------------------
# _CATEGORY_TO_DEVICE_CLASS mapping
# ---------------------------------------------------------------------------


class TestCategoryToDeviceClassMapping:

    @pytest.mark.parametrize(
        "category, expected_class",
        [
            (Category.AV_RECEIVER, MediaPlayerDeviceClass.RECEIVER),
            (Category.STEREO_RECEIVER, MediaPlayerDeviceClass.RECEIVER),
            (Category.SOUNDBAR, MediaPlayerDeviceClass.SPEAKER),
            (Category.SUBWOOFER, MediaPlayerDeviceClass.SPEAKER),
            (Category.MINI_SYSTEM, MediaPlayerDeviceClass.SPEAKER),
            (Category.DESKTOP_AUDIO_1, MediaPlayerDeviceClass.SPEAKER),
        ],
    )
    def test_known_categories(self, category, expected_class):
        assert _CATEGORY_TO_DEVICE_CLASS[category] == expected_class

    def test_unknown_not_in_mapping(self):
        assert _CATEGORY_TO_DEVICE_CLASS.get(Category.UNKNOWN) is None

    def test_all_non_unknown_categories_covered(self):
        for cat in Category:
            if cat != Category.UNKNOWN:
                assert cat in _CATEGORY_TO_DEVICE_CLASS, f"{cat} missing from mapping"


# ---------------------------------------------------------------------------
# MusicCastMediaPlayer.device_class and .icon
# ---------------------------------------------------------------------------


class TestMusicCastMediaPlayerDeviceClassAndIcon:

    @pytest.mark.parametrize(
        "category, expected_class",
        [
            (Category.AV_RECEIVER, MediaPlayerDeviceClass.RECEIVER),
            (Category.STEREO_RECEIVER, MediaPlayerDeviceClass.RECEIVER),
            (Category.SOUNDBAR, MediaPlayerDeviceClass.SPEAKER),
            (Category.SUBWOOFER, MediaPlayerDeviceClass.SPEAKER),
            (Category.MINI_SYSTEM, MediaPlayerDeviceClass.SPEAKER),
            (Category.DESKTOP_AUDIO_1, MediaPlayerDeviceClass.SPEAKER),
            (Category.UNKNOWN, None),
        ],
    )
    def test_device_class(self, mock_coordinator, category, expected_class):
        mock_coordinator.data.category = category
        player = make_player(mock_coordinator)

        assert player.device_class == expected_class

    @pytest.mark.parametrize(
        "category, expected_icon",
        [
            (Category.AV_RECEIVER, "mdi:audio-video"),
            (Category.STEREO_RECEIVER, "mdi:audio-video"),
            (Category.SOUNDBAR, "mdi:speaker"),
            (Category.SUBWOOFER, "mdi:speaker"),
            (Category.MINI_SYSTEM, "mdi:speaker"),
            (Category.DESKTOP_AUDIO_1, "mdi:speaker"),
            (Category.UNKNOWN, "mdi:speaker"),  # fallback
        ],
    )
    def test_icon(self, mock_coordinator, category, expected_icon):
        mock_coordinator.data.category = category
        player = make_player(mock_coordinator)

        assert player.icon == expected_icon
