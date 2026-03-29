"""Tests for the yamaha_musiccast select platform.

Covers both select entity classes defined in select.py:

  SelectableCapability  — wraps an OptionSetter capability; used for things
                          like speaker pattern selection.
  ZoneSceneSelect       — stores a named zone scene without activating it;
                          activation is deferred to ZoneSceneButton.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.yamaha_musiccast.aiomusiccast.capabilities import (
    EntityType,
    OptionSetter,
    Scene,
)
from custom_components.yamaha_musiccast.const import TRANSLATION_KEY_MAPPING
from custom_components.yamaha_musiccast.select import SelectableCapability, ZoneSceneSelect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_speaker_pattern_cap(current: int = 0, patterns: list[int] | None = None) -> OptionSetter:
    if patterns is None:
        patterns = [0, 1, 2]
    return OptionSetter(
        "SPEAKER_PATTERN",
        "Speaker Pattern",
        EntityType.CONFIG,
        lambda: current,
        AsyncMock(),
        {num: f"pattern_{num}" for num in patterns},
    )


def make_scene(num: int, title: str, zone_id: str = "main") -> Scene:
    return Scene(
        f"{zone_id}_scene_{num}",
        num,
        lambda n, t=title: t,
        EntityType.CONFIG,
        AsyncMock(),
    )


# ===========================================================================
# SelectableCapability (e.g. speaker pattern)
# ===========================================================================


class TestSelectableCapability:
    """Tests for SelectableCapability — the generic OptionSetter select entity."""

    # --- Options list ---

    def test_options_built_from_capability(self, mock_coordinator):
        cap = make_speaker_pattern_cap(patterns=[0, 1, 2])
        entity = SelectableCapability(mock_coordinator, cap)

        assert entity._attr_options == ["pattern_0", "pattern_1", "pattern_2"]

    def test_options_reflect_capability_pattern_list(self, mock_coordinator):
        cap = make_speaker_pattern_cap(patterns=[0, 3, 7])
        entity = SelectableCapability(mock_coordinator, cap)

        assert entity._attr_options == ["pattern_0", "pattern_3", "pattern_7"]

    # --- Current option ---

    def test_current_option_maps_value_to_label(self, mock_coordinator):
        cap = make_speaker_pattern_cap(current=1)
        entity = SelectableCapability(mock_coordinator, cap)

        assert entity.current_option == "pattern_1"

    def test_current_option_is_none_when_value_not_in_options(self, mock_coordinator):
        cap = OptionSetter(
            "SPEAKER_PATTERN", "Speaker Pattern", EntityType.CONFIG,
            lambda: 99,
            AsyncMock(),
            {0: "pattern_0"},
        )
        entity = SelectableCapability(mock_coordinator, cap)

        assert entity.current_option is None

    # --- Translation key and unique ID ---

    def test_translation_key_set_from_mapping(self, mock_coordinator):
        cap = make_speaker_pattern_cap()
        entity = SelectableCapability(mock_coordinator, cap)

        assert entity._attr_translation_key == TRANSLATION_KEY_MAPPING.get("SPEAKER_PATTERN")
        assert entity._attr_translation_key == "speaker_pattern"

    def test_unique_id_combines_device_and_capability(self, mock_coordinator):
        cap = make_speaker_pattern_cap()
        entity = SelectableCapability(mock_coordinator, cap)

        assert entity.unique_id == "TEST_DEVICE_ID_SPEAKER_PATTERN"

    def test_zone_capability_unique_id_includes_zone_suffix(self, mock_coordinator):
        zone = MagicMock()
        zone.name = "Zone 2"
        zone.capabilities = []
        mock_coordinator.data.zones["zone2"] = zone

        cap = make_speaker_pattern_cap()
        entity = SelectableCapability(mock_coordinator, cap, zone_id="zone2")

        assert entity.unique_id == "TEST_DEVICE_ID_zone2_SPEAKER_PATTERN"

    # --- Option selection ---

    @pytest.mark.asyncio
    async def test_select_option_passes_numeric_key_not_label(self, mock_coordinator):
        """async_select_option must forward the numeric key, not the display string."""
        set_mock = AsyncMock()
        cap = OptionSetter(
            "SPEAKER_PATTERN", "Speaker Pattern", EntityType.CONFIG,
            lambda: 0, set_mock, {0: "pattern_0", 1: "pattern_1"},
        )
        entity = SelectableCapability(mock_coordinator, cap)

        await entity.async_select_option("pattern_1")

        set_mock.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_select_option_rejects_unknown_label(self, mock_coordinator):
        cap = make_speaker_pattern_cap(patterns=[0, 1])
        entity = SelectableCapability(mock_coordinator, cap)

        with pytest.raises((KeyError, ValueError)):
            await entity.async_select_option("pattern_99")

    @pytest.mark.asyncio
    async def test_translation_key_refreshed_after_select(self, mock_coordinator):
        set_mock = AsyncMock()
        cap = OptionSetter(
            "SPEAKER_PATTERN", "Speaker Pattern", EntityType.CONFIG,
            lambda: 0, set_mock, {0: "pattern_0", 1: "pattern_1"},
        )
        entity = SelectableCapability(mock_coordinator, cap)
        await entity.async_select_option("pattern_0")

        assert entity._attr_translation_key == TRANSLATION_KEY_MAPPING.get("SPEAKER_PATTERN")


# ===========================================================================
# ZoneSceneSelect
# ===========================================================================


class TestZoneSceneSelect:
    """Tests for ZoneSceneSelect — deferred scene selection entity."""

    # --- Initialisation ---

    def test_options_built_from_zone_capabilities(self, mock_coordinator):
        s1 = make_scene(1, "Morning")
        s2 = make_scene(2, "Evening")
        mock_coordinator.data.zones["main"].capabilities = [s1, s2]

        entity = ZoneSceneSelect(mock_coordinator, "main")

        assert entity._attr_options == ["1: Morning", "2: Evening"]

    def test_non_scene_capabilities_ignored(self, mock_coordinator):
        s1 = make_scene(1, "Morning")
        mock_coordinator.data.zones["main"].capabilities = [s1, MagicMock()]

        entity = ZoneSceneSelect(mock_coordinator, "main")

        assert entity._attr_options == ["1: Morning"]

    def test_initial_option_from_coordinator(self, mock_coordinator):
        s1 = make_scene(1, "Morning")
        mock_coordinator.data.zones["main"].capabilities = [s1]
        mock_coordinator.selected_scenes = {"main": s1}

        entity = ZoneSceneSelect(mock_coordinator, "main")

        assert entity._attr_current_option == s1.name

    def test_no_initial_option_when_none_stored(self, mock_coordinator):
        mock_coordinator.data.zones["main"].capabilities = [make_scene(1, "Morning")]
        mock_coordinator.selected_scenes = {}

        entity = ZoneSceneSelect(mock_coordinator, "main")

        assert entity._attr_current_option is None

    def test_unique_id(self, mock_coordinator):
        mock_coordinator.data.zones["main"].capabilities = [make_scene(1, "M")]

        entity = ZoneSceneSelect(mock_coordinator, "main")

        assert entity.unique_id == "TEST_DEVICE_ID_scene_select"

    # --- async_select_option ---

    @pytest.mark.asyncio
    async def test_select_option_stores_scene_in_coordinator(self, mock_coordinator):
        s1 = make_scene(1, "Morning")
        s2 = make_scene(2, "Evening")
        mock_coordinator.data.zones["main"].capabilities = [s1, s2]
        mock_coordinator.selected_scenes = {}

        entity = ZoneSceneSelect(mock_coordinator, "main")
        entity.async_write_ha_state = MagicMock()
        await entity.async_select_option("2: Evening")

        assert mock_coordinator.selected_scenes["main"] is s2

    @pytest.mark.asyncio
    async def test_select_option_updates_current_option(self, mock_coordinator):
        s1 = make_scene(1, "Morning")
        mock_coordinator.data.zones["main"].capabilities = [s1]
        mock_coordinator.selected_scenes = {}

        entity = ZoneSceneSelect(mock_coordinator, "main")
        entity.async_write_ha_state = MagicMock()
        await entity.async_select_option("1: Morning")

        assert entity._attr_current_option == "1: Morning"

    @pytest.mark.asyncio
    async def test_select_option_does_not_activate_scene(self, mock_coordinator):
        """Selection is deferred — activate() must not be called here."""
        activate_mock = AsyncMock()
        scene = Scene("main_scene_1", 1, lambda n: "Morning", EntityType.CONFIG, activate_mock)
        mock_coordinator.data.zones["main"].capabilities = [scene]
        mock_coordinator.selected_scenes = {}

        entity = ZoneSceneSelect(mock_coordinator, "main")
        entity.async_write_ha_state = MagicMock()
        await entity.async_select_option("1: Morning")

        activate_mock.assert_not_awaited()
