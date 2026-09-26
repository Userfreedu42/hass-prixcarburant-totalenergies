from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [Shortage(coordinator, station_id, fuel) for station_id, station in coordinator.data.items() for fuel in station.get("fuels", {})]
    )


class Shortage(BinarySensorEntity):
    _attr_device_class = "problem"

    def __init__(self, coordinator, station_id, fuel):
        self.coordinator = coordinator
        self.station_id = station_id
        self.fuel = fuel
        station = coordinator.data[station_id]
        label = station["fuels"][fuel]["label"]
        self._attr_name = f"{station['brand']} {station['name']} — {label} — Rupture"
        self._attr_unique_id = f"totalenergies_{station_id}_{fuel}_shortage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name=f"{station['brand']} — {station['name']}",
            manufacturer="TotalEnergies",
            model=station["brand"],
        )

    @property
    def available(self):
        return self.coordinator.last_update_success and self.station_id in self.coordinator.data

    @property
    def is_on(self):
        value = self.coordinator.data[self.station_id].get("fuels", {}).get(self.fuel, {})
        return bool(value.get("rupture"))

    @property
    def extra_state_attributes(self):
        value = self.coordinator.data[self.station_id].get("fuels", {}).get(self.fuel, {})
        return {
            "fuel": value.get("label"),
            "rupture_type": value.get("rupture_type"),
            "rupture_since": value.get("rupture_since"),
            "station_id": self.station_id,
        }
