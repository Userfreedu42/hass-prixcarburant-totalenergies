from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [Rupture(coordinator, station_id) for station_id in coordinator.data]
    )


class Rupture(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = "problem"
    _attr_should_poll = False

    def __init__(self, coordinator, station_id: str) -> None:
        super().__init__(coordinator)
        self.station_id = station_id
        self._attr_unique_id = f"totalenergies_{station_id}_rupture"
        self._attr_name = f"TotalEnergies {station_id} — Rupture"

    @property
    def is_on(self) -> bool:
        fuels = self.coordinator.data.get(self.station_id, {}).get("fuels", {})
        return any(fuel.get("rupture", False) for fuel in fuels.values())

    @property
    def extra_state_attributes(self):
        fuels = self.coordinator.data.get(self.station_id, {}).get("fuels", {})
        return {
            "ruptures": [
                fuel_name for fuel_name, fuel in fuels.items() if fuel.get("rupture", False)
            ]
        }
