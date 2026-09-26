from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FUEL_LABELS


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for station_id, station in coordinator.data.items():
        for fuel in station.get("fuels", {}):
            label = FUEL_LABELS.get(fuel)
            if not label:
                continue
            entities.append(Fuel(coordinator, station_id, fuel, label))
            entities.append(FuelStatus(coordinator, station_id, fuel, label))
    async_add_entities(entities)


class _BaseFuelEntity(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, station_id, fuel, label):
        super().__init__(coordinator)
        self.station_id = station_id
        self.fuel = fuel
        self.label = label
        station = coordinator.data[station_id]
        postal_code = str(station.get("postal_code") or "").strip()
        city = str(station.get("city") or "").strip()
        self.station_name = " — ".join(part for part in (postal_code, city) if part) or station_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name=self.station_name,
            manufacturer="TotalEnergies",
            model=station.get("brand", "TotalEnergies"),
        )

    @property
    def available(self):
        return self.coordinator.last_update_success and self.station_id in self.coordinator.data

    def _value(self):
        return self.coordinator.data.get(self.station_id, {}).get("fuels", {}).get(self.fuel, {})


class Fuel(_BaseFuelEntity):
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS

    def __init__(self, coordinator, station_id, fuel, label):
        super().__init__(coordinator, station_id, fuel, label)
        self._attr_name = label
        self._attr_unique_id = f"totalenergies_{station_id}_{fuel}"

    @property
    def native_value(self):
        return self._value().get("price")

    @property
    def extra_state_attributes(self):
        station = self.coordinator.data[self.station_id]
        value = self._value()
        return {
            "station_id": self.station_id,
            "statut": "Rupture" if value.get("rupture") else "Non",
            "rupture": bool(value.get("rupture")),
            "rupture_type": value.get("rupture_type"),
            "price_updated": value.get("updated"),
            "distance_km": station.get("distance_km"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "address": station.get("address"),
            "postal_code": station.get("postal_code"),
            "city": station.get("city"),
            "services": station.get("services", []),
        }


class FuelStatus(_BaseFuelEntity):
    """Text status: exactly 'Non' or 'Rupture'."""

    def __init__(self, coordinator, station_id, fuel, label):
        super().__init__(coordinator, station_id, fuel, label)
        self._attr_name = f"{label} — Rupture"
        self._attr_unique_id = f"totalenergies_{station_id}_{fuel}_status"
        self._attr_icon = "mdi:gas-station"

    @property
    def native_value(self):
        return "Rupture" if self._value().get("rupture") else "Non"

    @property
    def extra_state_attributes(self):
        value = self._value()
        return {
            "fuel": self.label,
            "rupture": bool(value.get("rupture")),
            "rupture_type": value.get("rupture_type"),
            "rupture_since": value.get("rupture_since"),
            "station_id": self.station_id,
        }
