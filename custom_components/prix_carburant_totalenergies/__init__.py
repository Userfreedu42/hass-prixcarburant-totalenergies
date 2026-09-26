from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_MINUTES, DOMAIN
from .data import fetch_nearby_total_stations, fetch_total_catalog, update_prices

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    cfg = entry.data | entry.options
    try:
        catalog = await fetch_total_catalog(session)
        stations = await fetch_nearby_total_stations(
            session, catalog, float(cfg["latitude"]), float(cfg["longitude"]), float(cfg["radius_km"])
        )
    except Exception as err:
        raise HomeAssistantError(f"Impossible de charger les stations Total : {err}") from err

    if not stations:
        raise HomeAssistantError("Aucune station TotalEnergies trouvée dans le rayon configuré")

    _LOGGER.info("%s stations Total trouvées dans un rayon de %s km", len(stations), cfg["radius_km"])
    coordinator = TotalCoordinator(hass, session, stations, int(cfg.get("scan_interval", DEFAULT_SCAN_MINUTES)))
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok


class TotalCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, session, stations, scan_minutes):
        self.session = session
        self.stations = stations
        super().__init__(hass, logger=_LOGGER, name=DOMAIN, update_interval=timedelta(minutes=scan_minutes))

    async def _async_update_data(self):
        try:
            return await update_prices(self.session, self.stations)
        except Exception as err:
            raise UpdateFailed(f"Impossible de récupérer les prix TotalEnergies : {err}") from err
