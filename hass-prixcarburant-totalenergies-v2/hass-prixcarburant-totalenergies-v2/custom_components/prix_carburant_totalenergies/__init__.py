from __future__ import annotations

import io
import logging
import math
import xml.etree.ElementTree as ET
import zipfile
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, DEFAULT_SCAN_MINUTES, INSTANT_URL

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor"]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _coord(value: str | None) -> float | None:
    """Convert the government PTV_GEODECIMAL coordinate to WGS84."""
    if value is None:
        return None
    try:
        # The official open-data feed stores lat/lon multiplied by 100000.
        return float(value) / 100000
    except (TypeError, ValueError):
        return None


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    x = math.radians(lat2 - lat1)
    y = math.radians(lon2 - lon1)
    q = math.sin(x / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(y / 2) ** 2
    return 2 * r * math.asin(math.sqrt(q))


def _fuel_key(name: str) -> str | None:
    name = name.strip().lower().replace("-", "")
    if "gazole" in name:
        return "gazole"
    if name == "sp95":
        return "sp95"
    if name == "sp98":
        return "sp98"
    if name in ("e10", "sp95e10") or "e10" in name:
        return "e10"
    if name == "e85" or "e85" in name:
        return "e85"
    if "gpl" in name:
        return "gplc"
    return None


def parse(raw: bytes, cfg: dict) -> dict:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml_name = next(
            name for name in archive.namelist() if name.lower().endswith(".xml")
        )
        root = ET.fromstring(archive.read(xml_name))

    wanted = {str(station) for station in cfg.get("stations", [])}
    lat0 = float(cfg["latitude"])
    lon0 = float(cfg["longitude"])
    radius = float(cfg["radius_km"])
    out: dict[str, dict] = {}

    for pdv in root.iter():
        if _local(pdv.tag) != "pdv":
            continue

        attrs = {_local(k): v for k, v in pdv.attrib.items()}
        station_id = str(attrs.get("id", ""))
        lat = _coord(attrs.get("latitude"))
        lon = _coord(attrs.get("longitude"))
        if not station_id or lat is None or lon is None:
            continue

        dist = distance(lat0, lon0, lat, lon)
        if wanted:
            if station_id not in wanted:
                continue
        elif dist > radius:
            continue

        fuels: dict[str, dict] = {}

        # Prices currently published by the government feed.
        for element in pdv.iter():
            if _local(element.tag) != "prix":
                continue
            fuel = _fuel_key(element.attrib.get("nom", ""))
            if fuel is None:
                continue

            raw_price = (element.attrib.get("valeur") or "").strip().replace(",", ".")
            try:
                price = float(raw_price) if raw_price else None
            except ValueError:
                price = None

            fuels[fuel] = {
                "price": price,
                "price_status": "available" if price is not None else "unknown",
                "updated": element.attrib.get("maj"),
                "rupture": False,
                "rupture_type": None,
                "rupture_start": None,
                "rupture_end": None,
            }

        # The *_ruptures feed explicitly exposes stock outages/non-distribution.
        # Keep the price, when present, but mark the fuel as unavailable.
        for element in pdv.iter():
            if _local(element.tag) != "rupture":
                continue
            fuel = _fuel_key(element.attrib.get("fuel", ""))
            if fuel is None:
                continue
            current = fuels.setdefault(
                fuel,
                {
                    "price": None,
                    "price_status": "rupture",
                    "updated": None,
                    "rupture": True,
                    "rupture_type": None,
                    "rupture_start": None,
                    "rupture_end": None,
                },
            )
            current.update(
                {
                    "rupture": True,
                    "price_status": "rupture",
                    "rupture_type": element.attrib.get("type"),
                    "rupture_start": element.attrib.get("debut"),
                    "rupture_end": element.attrib.get("fin"),
                }
            )

        out[station_id] = {
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "distance_km": round(dist, 2),
            "postal_code": attrs.get("cp"),
            "address": _text(pdv, "adresse"),
            "city": _text(pdv, "ville"),
            "fuels": fuels,
            "services": sorted(
                {
                    (element.text or "").strip()
                    for element in pdv.iter()
                    if _local(element.tag) == "service"
                    and element.text
                    and element.text.strip()
                }
            ),
        }

    return out


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = Coordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        raise ConfigEntryNotReady(f"Unable to download fuel prices: {err}") from err

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok


class Coordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get("scan_interval", DEFAULT_SCAN_MINUTES)
            ),
        )
        self.entry = entry

    async def _async_update_data(self) -> dict:
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(INSTANT_URL) as response:
                    response.raise_for_status()
                    raw = await response.read()
            return await self.hass.async_add_executor_job(parse, raw, self.entry.data)
        except Exception as err:
            raise UpdateFailed(str(err)) from err
