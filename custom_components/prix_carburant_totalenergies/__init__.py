from __future__ import annotations

import io
import logging
import math
import zipfile
import xml.etree.ElementTree as ET
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_MINUTES, INSTANT_URL

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor"]
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TOTAL_BRANDS = {
    "total", "totalenergies", "total energies", "totalenergies access",
    "total energies access", "total access", "total contact",
}


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _text(element, name):
    for child in list(element):
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _coord(value):
    try:
        number = float(str(value).replace(",", "."))
        return number / 100000 if abs(number) > 180 else number
    except (TypeError, ValueError):
        return None


def distance(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    x = math.radians(lat2 - lat1)
    y = math.radians(lon2 - lon1)
    q = math.sin(x / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(y / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(q))


def _normalise(value):
    return " ".join((value or "").lower().replace("-", " ").split())


def _is_total(value):
    value = _normalise(value)
    return any(brand in value for brand in TOTAL_BRANDS)


def _fuel_key(name):
    name = (name or "").lower().replace(" ", "")
    if "gazole" in name or name == "diesel": return "gazole"
    if "sp95-e10" in name or "e10" in name: return "e10"
    if "sp98" in name: return "sp98"
    if "sp95" in name: return "sp95"
    if "e85" in name: return "e85"
    if "gpl" in name: return "gplc"
    return None


async def _get_total_station_coordinates(hass, latitude, longitude, radius_km):
    radius_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:30];
    (
      nwr[amenity=fuel][brand~\"Total|TotalEnergies|Total Access|Total Contact\",i](around:{radius_m},{latitude},{longitude});
      nwr[amenity=fuel][operator~\"Total|TotalEnergies|Total Access|Total Contact\",i](around:{radius_m},{latitude},{longitude});
      nwr[amenity=fuel][name~\"Total|TotalEnergies|Total Access|Total Contact\",i](around:{radius_m},{latitude},{longitude});
    );
    out center tags;
    """
    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OVERPASS_URL, data=query) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
    except Exception as err:
        _LOGGER.warning("Impossible de récupérer les stations TotalEnergies via OpenStreetMap: %s", err)
        return None

    stations = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        if not any(_is_total(tags.get(key, "")) for key in ("brand", "operator", "name")):
            continue
        lat = element.get("lat")
        lon = element.get("lon")
        if lat is None or lon is None:
            center = element.get("center", {})
            lat, lon = center.get("lat"), center.get("lon")
        if lat is not None and lon is not None:
            stations.append((float(lat), float(lon), tags))
    return stations


def parse(raw, cfg, total_stations):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
        root = ET.fromstring(archive.read(xml_name))

    wanted = set(map(str, cfg.get("stations", [])))
    lat0, lon0 = float(cfg["latitude"]), float(cfg["longitude"])
    radius = float(cfg["radius_km"])
    result = {}

    # If OSM is temporarily unavailable, do not silently expose other brands.
    # Keep the previous successful station list if one was supplied explicitly.
    if total_stations is None:
        return {}
    total_coords = [(lat, lon) for lat, lon, _ in total_stations]

    for pdv in root.iter():
        if _local(pdv.tag) != "pdv":
            continue
        attrs = {_local(k): v for k, v in pdv.attrib.items()}
        station_id = str(attrs.get("id", ""))
        lat, lon = _coord(attrs.get("latitude")), _coord(attrs.get("longitude"))
        if not station_id or lat is None or lon is None:
            continue
        dist = distance(lat0, lon0, lat, lon)
        if wanted:
            if station_id not in wanted:
                continue
        elif dist > radius:
            continue
        elif not total_coords or min(distance(lat, lon, a, b) for a, b in total_coords) > 1.0:
            continue

        fuels, ruptures = {}, set()
        for element in pdv.iter():
            tag = _local(element.tag)
            values = {_local(k): v for k, v in element.attrib.items()}
            if tag == "prix":
                fuel = _fuel_key(values.get("nom", ""))
                if not fuel: continue
                try: value = float(str(values.get("valeur", "")).replace(",", "."))
                except (ValueError, TypeError): value = None
                fuels[fuel] = {"price": value, "updated": values.get("maj")}
            elif tag == "rupture":
                fuel = _fuel_key(values.get("nom") or values.get("fuel") or values.get("type", ""))
                if fuel: ruptures.add(fuel)
        for fuel in ruptures:
            fuels.setdefault(fuel, {"price": None, "updated": None})["rupture"] = True
        result[station_id] = {
            "station_id": station_id, "latitude": lat, "longitude": lon,
            "distance_km": round(dist, 2), "postal_code": attrs.get("cp"),
            "address": _text(pdv, "adresse"), "city": _text(pdv, "ville"),
            "fuels": fuels,
            "services": sorted({(e.text or "").strip() for e in pdv.iter() if _local(e.tag) == "service" and e.text and e.text.strip()}),
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
    if unloaded: hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


class Coordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, logger=_LOGGER, name=DOMAIN,
            update_interval=timedelta(minutes=entry.options.get("scan_interval", DEFAULT_SCAN_MINUTES)))
        self.entry = entry

    async def _async_update_data(self):
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(INSTANT_URL) as response:
                    response.raise_for_status()
                    raw = await response.read()
            cfg = self.entry.data
            stations = await _get_total_station_coordinates(self.hass, float(cfg["latitude"]), float(cfg["longitude"]), float(cfg["radius_km"]))
            return await self.hass.async_add_executor_job(parse, raw, cfg, stations)
        except Exception as err:
            raise UpdateFailed(str(err)) from err
