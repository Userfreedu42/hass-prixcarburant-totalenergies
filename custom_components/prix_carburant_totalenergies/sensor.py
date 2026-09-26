from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, FUEL_LABELS


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for station_id, station in coordinator.data.items():
        for fuel in station.get("fuels", {}):
            label = FUEL_LABELS.get(fuel)
            if label:
                entities.append(Fuel(coordinator, station_id, fuel, label))
    async_add_entities(entities)


class Fuel(SensorEntity):
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS

    def __init__(self, coordinator, station_id, fuel, label):
        self.coordinator = coordinator
        self.station_id = station_id
        self.fuel = fuel
        station = coordinator.data[station_id]
        postal_code = str(station.get("postal_code") or "").strip()
        city = str(station.get("city") or "").strip()
        station_name = " — ".join(part for part in (postal_code, city) if part) or station_id
        # Le nom de l'entité carburant reste uniquement le nom du carburant.
        self._attr_name = label
        self._attr_unique_id = f"totalenergies_{station_id}_{fuel}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name=station_name,
            manufacturer="TotalEnergies",
            model=station.get("brand", "TotalEnergies"),
        )

    @property
    def available(self):
        return self.coordinator.last_update_success and self.station_id in self.coordinator.data

    @property
    def native_value(self):
        value = self.coordinator.data.get(self.station_id, {}).get("fuels", {}).get(self.fuel)
        return value.get("price") if value else None

    @property
    def extra_state_attributes(self):
        station = self.coordinator.data[self.station_id]
        value = station.get("fuels", {}).get(self.fuel, {})
        return {
            "station_id": self.station_id,
            "statut": "Rupture" if value.get("rupture") else "OK",
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
