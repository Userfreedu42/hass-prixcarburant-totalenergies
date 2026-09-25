from __future__ import annotations

import io
import math
import zipfile
import xml.etree.ElementTree as ET
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_MINUTES, INSTANT_URL

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor"]


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _text(element, name):
    for child in list(element):
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _coord(value):
    try:
        number = float(value)
        return number / 100000 if abs(number) > 180 else number
    except (TypeError, ValueError):
        return None


def distance(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    x = math.radians(lat2 - lat1)
    y = math.radians(lon2 - lon1)
    q = math.sin(x / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(y / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(q))


def parse(raw, cfg):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
        root = ET.fromstring(archive.read(xml_name))

    wanted = set(map(str, cfg.get("stations", [])))
    lat0 = cfg["latitude"]
    lon0 = cfg["longitude"]
    radius = cfg["radius_km"]
    result = {}

    for pdv in root.iter():
        if _local(pdv.tag) != "pdv":
            continue
        attrs = {_local(k): v for k, v in pdv.attrib.items()}
        station_id = str(attrs.get("id", ""))
        lat = _coord(attrs.get("latitude"))
        lon = _coord(attrs.get("longitude"))
        if lat is None or lon is None:
            continue

        dist = distance(lat0, lon0, lat, lon)
        if wanted and station_id not in wanted:
            continue
        if not wanted and dist > radius:
            continue

        fuels = {}
        for price in pdv.iter():
            if _local(price.tag) != "prix":
                continue
            values = {_local(k): v for k, v in price.attrib.items()}
            name = (values.get("nom") or "").lower()
            if "gazole" in name:
                fuel = "gazole"
            elif "sp95" in name and "e10" not in name:
                fuel = "sp95"
            elif "sp98" in name:
                fuel = "sp98"
            elif "e10" in name:
                fuel = "e10"
            elif "e85" in name:
                fuel = "e85"
            elif "gpl" in name:
                fuel = "gplc"
            else:
                continue
            try:
                value = float(values["valeur"].replace(",", ".")) if values.get("valeur") else "rupture"
            except (ValueError, TypeError):
                value = "rupture"
            fuels[fuel] = {"price": value, "updated": values.get("maj")}

        result[station_id] = {
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "distance_km": round(dist, 2),
            "postal_code": attrs.get("cp"),
            "address": _text(pdv, "adresse"),
            "city": _text(pdv, "ville"),
            "fuels": fuels,
            "services": sorted({
                (element.text or "").strip()
                for element in pdv.iter()
                if _local(element.tag) == "service" and element.text and element.text.strip()
            }),
        }
    return result


async def async_setup(hass: HomeAssistant, config):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = Coordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


class Coordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=entry.options.get("scan_interval", DEFAULT_SCAN_MINUTES)),
        )
        self.entry = entry

    async def _async_update_data(self):
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(INSTANT_URL) as response:
                    response.raise_for_status()
                    raw = await response.read()
            return await self.hass.async_add_executor_job(parse, raw, self.entry.data)
        except Exception as err:
            raise UpdateFailed(str(err)) from err
