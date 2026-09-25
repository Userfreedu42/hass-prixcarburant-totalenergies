from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FUEL_LABELS


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        Fuel(coordinator, station_id, fuel, label)
        for station_id in coordinator.data
        for fuel, label in FUEL_LABELS.items()
    ]
    async_add_entities(entities)


class Fuel(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_should_poll = False

    def __init__(self, coordinator, station_id: str, fuel: str, label: str) -> None:
        super().__init__(coordinator)
        self.station_id = station_id
        self.fuel = fuel
        self._attr_name = f"TotalEnergies {station_id} — {label}"
        self._attr_unique_id = f"totalenergies_{station_id}_{fuel}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name=f"TotalEnergies — {station_id}",
            manufacturer="TotalEnergies",
        )

    @property
    def native_value(self):
        fuel = self.coordinator.data.get(self.station_id, {}).get("fuels", {}).get(self.fuel)
        return fuel.get("price") if fuel and fuel.get("price_status") != "rupture" else None

    @property
    def extra_state_attributes(self):
        station = self.coordinator.data.get(self.station_id, {})
        fuel = station.get("fuels", {}).get(self.fuel, {})
        return {
            "station_id": self.station_id,
            "price_status": fuel.get("price_status", "unknown"),
            "price_updated": fuel.get("updated"),
            "rupture": fuel.get("rupture", False),
            "rupture_type": fuel.get("rupture_type"),
            "rupture_start": fuel.get("rupture_start"),
            "rupture_end": fuel.get("rupture_end"),
            "distance_km": station.get("distance_km"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "address": station.get("address"),
            "postal_code": station.get("postal_code"),
            "city": station.get("city"),
            "services": station.get("services", []),
        }
