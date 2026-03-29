"""Tests for the yamaha_musiccast number platform.

Covers NumberCapability — the generic NumberSetter entity wrapper, with
specific attention to the dB (actual volume) variant which gets additional
decoration: SIGNAL_STRENGTH device class, mdi:knob icon, disabled by default.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from homeassistant.components.number import NumberDeviceClass

from custom_components.yamaha_musiccast.aiomusiccast.capabilities import (
    EntityType,
    NumberSetter,
)
from custom_components.yamaha_musiccast.aiomusiccast.exceptions import MusicCastException
from custom_components.yamaha_musiccast.number import NumberCapability


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_actual_volume_cap(
    current: float = -20.0,
    min_val: float = -80.0,
    max_val: float = 0.0,
    step: float = 0.5,
    set_fn: AsyncMock | None = None,
) -> NumberSetter:
    return NumberSetter(
        "zone_ACTUAL_VOLUME",
        "Actual Volume",
        EntityType.REGULAR,
        lambda: current,
        set_fn or AsyncMock(),
        min_val,
        max_val,
        step,
        unit="dB",
    )


# ---------------------------------------------------------------------------
# NumberCapability — dB (actual volume) variant
# ---------------------------------------------------------------------------


class TestNumberCapabilityDb:
    """Tests for the dB-decorated NumberCapability (actual volume)."""

    # --- Entity decoration ---

    def test_device_class_is_signal_strength(self, mock_coordinator):
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(), zone_id="main")

        assert entity._attr_device_class == NumberDeviceClass.SIGNAL_STRENGTH

    def test_icon_is_knob(self, mock_coordinator):
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(), zone_id="main")

        assert entity._attr_icon == "mdi:knob"

    def test_disabled_by_default(self, mock_coordinator):
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(), zone_id="main")

        assert entity._attr_entity_registry_enabled_default is False

    # --- Range attributes ---

    def test_range_attributes_copied_from_capability(self, mock_coordinator):
        cap = make_actual_volume_cap(min_val=-80.0, max_val=0.0, step=0.5)
        entity = NumberCapability(mock_coordinator, cap, zone_id="main")

        assert entity._attr_native_min_value == -80.0
        assert entity._attr_native_max_value == 0.0
        assert entity._attr_native_step == 0.5

    def test_unit_of_measurement_is_db(self, mock_coordinator):
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(), zone_id="main")

        assert entity._attr_native_unit_of_measurement == "dB"

    # --- native_value ---

    def test_native_value_delegates_to_capability(self, mock_coordinator):
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(current=-35.5), zone_id="main")

        assert entity.native_value == -35.5

    def test_native_value_reflects_updated_value(self, mock_coordinator):
        readings = [-40.0]
        cap = NumberSetter(
            "zone_ACTUAL_VOLUME", "Actual Volume", EntityType.REGULAR,
            lambda: readings[0], AsyncMock(), -80.0, 0.0, 0.5, unit="dB",
        )
        entity = NumberCapability(mock_coordinator, cap, zone_id="main")

        assert entity.native_value == -40.0
        readings[0] = -30.0
        assert entity.native_value == -30.0

    # --- async_set_native_value ---

    @pytest.mark.asyncio
    async def test_set_native_value_calls_capability_set(self, mock_coordinator):
        set_mock = AsyncMock()
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(set_fn=set_mock), zone_id="main")

        await entity.async_set_native_value(-25.5)

        set_mock.assert_awaited_once_with(-25.5)

    @pytest.mark.asyncio
    async def test_set_native_value_rejects_above_max(self, mock_coordinator):
        set_mock = AsyncMock()
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(max_val=0.0, set_fn=set_mock), zone_id="main")

        with pytest.raises(MusicCastException):
            await entity.async_set_native_value(1.0)

        set_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_native_value_rejects_below_min(self, mock_coordinator):
        set_mock = AsyncMock()
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(min_val=-80.0, set_fn=set_mock), zone_id="main")

        with pytest.raises(MusicCastException):
            await entity.async_set_native_value(-81.0)

        set_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_native_value_rejects_off_step(self, mock_coordinator):
        set_mock = AsyncMock()
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(set_fn=set_mock), zone_id="main")

        with pytest.raises(MusicCastException):
            await entity.async_set_native_value(-20.3)

        set_mock.assert_not_awaited()

    # --- Unique ID ---

    def test_unique_id_for_default_zone(self, mock_coordinator):
        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(), zone_id="main")

        assert entity.unique_id == "TEST_DEVICE_ID_zone_ACTUAL_VOLUME"

    def test_unique_id_for_non_default_zone(self, mock_coordinator):
        from unittest.mock import MagicMock
        mock_coordinator.data.zones["zone2"] = MagicMock()

        entity = NumberCapability(mock_coordinator, make_actual_volume_cap(), zone_id="zone2")

        assert entity.unique_id == "TEST_DEVICE_ID_zone2_zone_ACTUAL_VOLUME"


# ---------------------------------------------------------------------------
# NumberCapability — no unit (generic number, no dB decoration)
# ---------------------------------------------------------------------------


class TestNumberCapabilityNoUnit:

    def test_no_special_decoration(self, mock_coordinator):
        cap = NumberSetter(
            "some_number", "Some Number", EntityType.REGULAR,
            lambda: 5, AsyncMock(), 0, 10, 1,
        )
        entity = NumberCapability(mock_coordinator, cap)

        assert getattr(entity, "_attr_device_class", None) is None
        assert entity._attr_icon != "mdi:knob"
        assert entity._attr_entity_registry_enabled_default is True
