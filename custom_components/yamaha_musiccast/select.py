"""The select entities for musiccast."""

from __future__ import annotations

from .aiomusiccast.capabilities import OptionSetter, Scene

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, TRANSLATION_KEY_MAPPING
from .coordinator import MusicCastDataUpdateCoordinator
from .entity import MusicCastCapabilityEntity, MusicCastDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MusicCast select entities based on a config entry."""
    coordinator: MusicCastDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    select_entities = [
        SelectableCapability(coordinator, capability)
        for capability in coordinator.data.capabilities
        if isinstance(capability, OptionSetter)
    ]

    select_entities.extend(
        SelectableCapability(coordinator, capability, zone)
        for zone, data in coordinator.data.zones.items()
        for capability in data.capabilities
        if isinstance(capability, OptionSetter)
    )

    select_entities.extend(
        ZoneSceneSelect(coordinator, zone_id)
        for zone_id, data in coordinator.data.zones.items()
        if any(isinstance(c, Scene) for c in data.capabilities)
    )

    async_add_entities(select_entities)


class SelectableCapability(MusicCastCapabilityEntity, SelectEntity):
    """Representation of a MusicCast Select entity."""

    capability: OptionSetter

    def __init__(
        self,
        coordinator: MusicCastDataUpdateCoordinator,
        capability: OptionSetter,
        zone_id: str | None = None,
    ) -> None:
        """Initialize the MusicCast Select entity."""
        MusicCastCapabilityEntity.__init__(self, coordinator, capability, zone_id)
        self._attr_options = list(capability.options.values())
        self._attr_translation_key = TRANSLATION_KEY_MAPPING.get(capability.id)

    async def async_select_option(self, option: str) -> None:
        """Select the given option."""
        value = {val: key for key, val in self.capability.options.items()}[option]
        await self.capability.set(value)
        self._attr_translation_key = TRANSLATION_KEY_MAPPING.get(self.capability.id)

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self.capability.options.get(self.capability.current)


class ZoneSceneSelect(MusicCastDeviceEntity, SelectEntity):
    """Select entity to choose a zone scene without activating it immediately."""

    def __init__(
        self,
        coordinator: MusicCastDataUpdateCoordinator,
        zone_id: str,
    ) -> None:
        """Initialize the zone scene select."""
        self._zone_id = zone_id
        self._scenes: dict[str, Scene] = {
            cap.name: cap
            for cap in coordinator.data.zones[zone_id].capabilities
            if isinstance(cap, Scene)
        }
        super().__init__(name="Scene", icon="mdi:palette", coordinator=coordinator)
        self._attr_options = list(self._scenes.keys())
        selected = coordinator.selected_scenes.get(zone_id)
        self._attr_current_option = selected.name if selected is not None else None

    @property
    def unique_id(self) -> str:
        """Return the unique ID for this entity."""
        return f"{self.device_id}_scene_select"

    async def async_select_option(self, option: str) -> None:
        """Store the selected scene; activate via the Activate Scene button."""
        self.coordinator.selected_scenes[self._zone_id] = self._scenes[option]
        self._attr_current_option = option
        self.async_write_ha_state()
