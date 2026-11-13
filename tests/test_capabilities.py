"""Tests for the capability classes."""

from unittest.mock import AsyncMock

import pytest

from aiomusiccast_co.capabilities import BinarySetter, EntityType, NumberSetter, OptionSetter, Scene, TextSensor
from aiomusiccast_co.exceptions import MusicCastException


def test_stateful_capability_reads_live_value() -> None:
    state = {"value": "a"}
    sensor = TextSensor("id", "Name", EntityType.DIAGNOSTIC, lambda: state["value"])

    state["value"] = "b"

    assert (sensor.id, sensor.name, sensor.entity_type, sensor.current) == ("id", "Name", EntityType.DIAGNOSTIC, "b")


async def test_number_setter_sets_value_in_range() -> None:
    set_value = AsyncMock()
    setter = NumberSetter("id", "Volume", EntityType.REGULAR, lambda: 0, set_value, -80.5, 16.5, 0.5, unit="dB")

    await setter.set(-20.5)

    set_value.assert_awaited_once_with(-20.5)
    assert setter.unit == "dB"


@pytest.mark.parametrize("value", [-81, 17, -20.25])
async def test_number_setter_rejects_out_of_range(value: float) -> None:
    set_value = AsyncMock()
    setter = NumberSetter("id", "Volume", EntityType.REGULAR, lambda: 0, set_value, -80.5, 16.5, 0.5)

    with pytest.raises(MusicCastException):
        await setter.set(value)
    set_value.assert_not_awaited()


async def test_option_setter_accepts_known_option() -> None:
    set_value = AsyncMock()
    setter = OptionSetter("id", "Sleep", EntityType.CONFIG, lambda: 0, set_value, {0: "off", 30: "30_min"})

    await setter.set(30)

    set_value.assert_awaited_once_with(30)


async def test_option_setter_rejects_unknown_option() -> None:
    set_value = AsyncMock()
    setter = OptionSetter("id", "Sleep", EntityType.CONFIG, lambda: 0, set_value, {0: "off"})

    with pytest.raises(ValueError, match="not a valid option"):
        await setter.set(45)
    set_value.assert_not_awaited()


async def test_binary_setter_accepts_bool() -> None:
    set_value = AsyncMock()
    setter = BinarySetter("id", "Enhancer", EntityType.CONFIG, lambda: False, set_value)

    await setter.set(True)

    set_value.assert_awaited_once_with(True)


async def test_binary_setter_rejects_non_bool() -> None:
    set_value = AsyncMock()
    setter = BinarySetter("id", "Enhancer", EntityType.CONFIG, lambda: False, set_value)

    with pytest.raises(ValueError, match="not a boolean"):
        await setter.set(1)
    set_value.assert_not_awaited()


async def test_scene_name_and_activation() -> None:
    names = {2: "Movie"}
    activate = AsyncMock()
    scene = Scene("zone_SCENE_2", 2, names.__getitem__, EntityType.CONFIG, activate)

    assert scene.name == "2: Movie"
    names[2] = "Party"
    assert scene.name == "2: Party"

    await scene.activate()
    activate.assert_awaited_once_with()
