from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for station_id, station in coordinator.data.items():
        for fuel in station.get("fuels", {}):
            entities.append(Fuel(coordinator, station_id, fuel))
    async_add_entities(entities)


class Fuel(SensorEntity):
    _attr_native_unit_of_measurement = "€/L"

    def __init__(self, coordinator, station_id, fuel):
        self.coordinator = coordinator
        self.station_id = station_id
        self.fuel = fuel
        station = coordinator.data[station_id]
        label = station["fuels"][fuel]["label"]
        self._attr_name = f"{station['brand']} {station['name']} — {label}"
        self._attr_unique_id = f"totalenergies_{station_id}_{fuel}_price"
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
    def native_value(self):
        return self.coordinator.data[self.station_id].get("fuels", {}).get(self.fuel, {}).get("price")

    @property
    def extra_state_attributes(self):
        station = self.coordinator.data[self.station_id]
        value = station.get("fuels", {}).get(self.fuel, {})
        services = station.get("services", {})
        if isinstance(services, dict):
            services = services.get("service", [])
        return {
            "station_id": self.station_id,
            "brand": station.get("brand"),
            "station_name": station.get("name"),
            "status": "rupture" if value.get("rupture") else "disponible",
            "rupture": value.get("rupture", False),
            "rupture_type": value.get("rupture_type"),
            "rupture_since": value.get("rupture_since"),
            "price_updated": value.get("updated"),
            "distance_km": station.get("distance_km"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "address": station.get("address"),
            "postal_code": station.get("postal_code"),
            "city": station.get("city"),
            "services": services,
            "totalenergies_stations_url": "https://services.totalenergies.fr/stations",
            "price_source": "data.gouv.fr / Ministère de l'Économie",
        }
