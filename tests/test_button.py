"""Tests for the yamaha_musiccast button platform.

Covers ZoneSceneButton — activates whichever scene is currently stored in
the coordinator for the zone. Unavailable until a scene has been selected
via ZoneSceneSelect.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.yamaha_musiccast.aiomusiccast.capabilities import EntityType, Scene
from custom_components.yamaha_musiccast.button import ZoneSceneButton


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_scene(num: int, title: str, zone_id: str = "main") -> Scene:
    return Scene(
        f"{zone_id}_scene_{num}",
        num,
        lambda n, t=title: t,
        EntityType.CONFIG,
        AsyncMock(),
    )


# ---------------------------------------------------------------------------
# ZoneSceneButton
# ---------------------------------------------------------------------------


class TestZoneSceneButton:
    """Tests for ZoneSceneButton."""

    # --- Availability ---

    def test_unavailable_without_stored_scene(self, mock_coordinator):
        mock_coordinator.selected_scenes = {}

        btn = ZoneSceneButton(mock_coordinator, "main")

        assert not btn.available

    def test_available_once_scene_is_stored(self, mock_coordinator):
        mock_coordinator.selected_scenes = {"main": make_scene(1, "Morning")}

        btn = ZoneSceneButton(mock_coordinator, "main")

        assert btn.available

    def test_unavailable_when_scene_stored_for_different_zone(self, mock_coordinator):
        mock_coordinator.selected_scenes = {"zone2": make_scene(1, "Morning", zone_id="zone2")}

        btn = ZoneSceneButton(mock_coordinator, "main")

        assert not btn.available

    # --- Unique ID ---

    def test_unique_id(self, mock_coordinator):
        btn = ZoneSceneButton(mock_coordinator, "main")

        assert btn.unique_id == "TEST_DEVICE_ID_scene_activate"

    # --- async_press ---

    @pytest.mark.asyncio
    async def test_press_activates_stored_scene(self, mock_coordinator):
        activate_mock = AsyncMock()
        scene = Scene("main_scene_1", 1, lambda n: "Morning", EntityType.CONFIG, activate_mock)
        mock_coordinator.selected_scenes = {"main": scene}
        mock_coordinator.async_request_refresh = AsyncMock()

        btn = ZoneSceneButton(mock_coordinator, "main")
        await btn.async_press()

        activate_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_press_requests_coordinator_refresh(self, mock_coordinator):
        activate_mock = AsyncMock()
        scene = Scene("main_scene_1", 1, lambda n: "Morning", EntityType.CONFIG, activate_mock)
        mock_coordinator.selected_scenes = {"main": scene}
        mock_coordinator.async_request_refresh = AsyncMock()

        btn = ZoneSceneButton(mock_coordinator, "main")
        await btn.async_press()

        mock_coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_press_noop_when_no_scene_selected(self, mock_coordinator):
        mock_coordinator.selected_scenes = {}
        mock_coordinator.async_request_refresh = AsyncMock()

        btn = ZoneSceneButton(mock_coordinator, "main")
        await btn.async_press()

        mock_coordinator.async_request_refresh.assert_not_awaited()
