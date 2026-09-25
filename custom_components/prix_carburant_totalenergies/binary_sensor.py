from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Rupture(coordinator, station_id) for station_id in coordinator.data])


class Rupture(BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, station_id):
        self.coordinator = coordinator
        self.station_id = station_id
        self._attr_unique_id = f"totalenergies_{station_id}_rupture"
        self._attr_name = f"TotalEnergies {station_id} — Rupture"

    @property
    def available(self):
        return self.coordinator.last_update_success and self.station_id in self.coordinator.data

    @property
    def is_on(self):
        return any(
            value.get("price") == "rupture"
            for value in self.coordinator.data[self.station_id].get("fuels", {}).values()
        )

    @property
    def extra_state_attributes(self):
        return {
            "ruptures": [
                fuel
                for fuel, value in self.coordinator.data[self.station_id].get("fuels", {}).items()
                if value.get("price") == "rupture"
            ]
        }
