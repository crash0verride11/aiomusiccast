"""The button entities for musiccast."""

from __future__ import annotations

from .aiomusiccast.capabilities import Scene

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import MusicCastDataUpdateCoordinator
from .entity import MusicCastDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MusicCast button entities based on a config entry."""
    coordinator: MusicCastDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        ZoneSceneButton(coordinator, zone_id)
        for zone_id, data in coordinator.data.zones.items()
        if any(isinstance(c, Scene) for c in data.capabilities)
    )


class ZoneSceneButton(MusicCastDeviceEntity, ButtonEntity):
    """Button that activates whichever scene is currently selected for the zone."""

    def __init__(
        self,
        coordinator: MusicCastDataUpdateCoordinator,
        zone_id: str,
    ) -> None:
        """Initialize the zone scene activate button."""
        self._zone_id = zone_id
        super().__init__(
            name="Set Scene",
            icon="mdi:play-box-multiple",
            coordinator=coordinator,
        )

    @property
    def unique_id(self) -> str:
        """Return the unique ID for this entity."""
        return f"{self.device_id}_scene_activate"

    @property
    def available(self) -> bool:
        """Only available once a scene has been selected."""
        return (
            super().available
            and self.coordinator.selected_scenes.get(self._zone_id) is not None
        )

    async def async_press(self) -> None:
        """Activate the currently selected scene."""
        scene = self.coordinator.selected_scenes.get(self._zone_id)
        if scene is not None:
            await scene.activate()
            await self.coordinator.async_request_refresh()
