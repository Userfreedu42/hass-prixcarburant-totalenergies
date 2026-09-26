from __future__ import annotations

import bz2
import csv
import io
import json
import logging
import unicodedata
from math import asin, cos, radians, sin, sqrt

import aiohttp

_LOGGER = logging.getLogger(__name__)
STATIONS_CATALOG_URL = "https://www.data.gouv.fr/api/1/datasets/r/fcab3bd4-6c6d-4b73-95d2-cfd5e04ee651"
PRICE_API_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records"
PAGE_SIZE = 100
TOTAL_BRANDS = {"total", "total energies", "totalenergies", "total access", "totalaccess", "total contact", "totalcontact", "totalenergies access", "total energies access"}
FUELS = {"gazole": "Gazole", "sp95": "SP95", "sp98": "SP98", "e10": "E10", "e85": "E85", "gplc": "GPLc"}
INVALID_STATUS = {"", "inconnu", "unknown", "probleme", "problem", "erreur", "error", "undefined", "null"}


def _norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(value.lower().replace("-", " ").split())


def _fuel_key(value: str | None) -> str | None:
    aliases = {
        "gazole": "gazole", "diesel": "gazole", "diesel premier": "gazole", "gazole premier": "gazole",
        "sp95": "sp95", "sans plomb 95": "sp95",
        "sp95 e10": "e10", "sp95 e 10": "e10", "sans plomb e10": "e10", "sans plomb 95 e10": "e10", "e10": "e10",
        "sp98": "sp98", "sans plomb 98": "sp98", "excellium sp98": "sp98",
        "e85": "e85", "superethanol e85": "e85",
        "gplc": "gplc", "gpl": "gplc", "lpg": "gplc",
    }
    return aliases.get(_norm(value))


def _is_total(*values: str | None) -> bool:
    return any(_norm(v) in TOTAL_BRANDS for v in values if v)


def _parse_names(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return set()
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else [parsed]
        except (TypeError, ValueError):
            items = text.split(";")
    result = set()
    for item in items:
        if isinstance(item, dict):
            item = item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel") or ""
        key = _fuel_key(str(item))
        if key:
            result.add(key)
    return result


def _parse_rupture_field(raw) -> dict[str, dict]:
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return {}
    result = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = _fuel_key(item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel"))
        if not key:
            continue
        rupture_type = item.get("@type") or item.get("type")
        if _norm(str(rupture_type)) in INVALID_STATUS:
            rupture_type = None
        result[key] = {
            "type": rupture_type,
            "since": item.get("@debut") or item.get("debut"),
            "end": item.get("@fin") or item.get("fin"),
        }
    return result


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(p1) * cos(p2) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def parse_catalog(raw: bytes) -> dict[str, dict[str, str]]:
    text = bz2.decompress(raw).decode("utf-8-sig")
    result = {}
    for row in csv.DictReader(io.StringIO(text)):
        raw_ids = (row.get("ref:FR:prix-carburants") or row.get("ref:FR:PrixCarburants") or "").strip()
        if not raw_ids or raw_ids.startswith("DELETE TAG"):
            continue
        brand = (row.get("brand") or "").strip()
        operator = (row.get("operator") or "").strip()
        branch = (row.get("branch") or "").strip()
        if not _is_total(brand, operator, branch):
            continue
        name = (row.get("name") or "").strip()
        for station_id in raw_ids.split(";"):
            station_id = station_id.strip()
            if station_id:
                result.setdefault(station_id, {"name": name, "brand": brand or operator or branch or "TotalEnergies"})
    return result


async def fetch_total_catalog(session: aiohttp.ClientSession):
    async with session.get(STATIONS_CATALOG_URL) as response:
        response.raise_for_status()
        catalog = parse_catalog(await response.read())
    if not catalog:
        raise RuntimeError("Aucune station Total trouvée dans stations-service")
    _LOGGER.debug("Catalogue stations-service: %s stations Total", len(catalog))
    return catalog


async def _api_get(session: aiohttp.ClientSession, params: dict) -> dict:
    async with session.get(PRICE_API_URL, params=params) as response:
        response.raise_for_status()
        return await response.json()


def _ids_where(ids: list[str]) -> str:
    # Le champ `id` du flux officiel est un entier (pas un texte).
    # Opendatasoft renvoie HTTP 400 si on compare cet entier à des chaînes.
    numeric_ids = []
    for value in ids:
        try:
            numeric_ids.append(str(int(value)))
        except (TypeError, ValueError):
            continue
    if not numeric_ids:
        return "id = -1"
    return "id IN (" + ",".join(numeric_ids) + ")"


async def fetch_nearby_total_stations(session, catalog, latitude, longitude, radius_km):
    where = f"distance(geom, geom'POINT({longitude} {latitude})', {radius_km}km)"
    count = await _api_get(session, {"select": "id", "where": where, "limit": 1})
    total_count = int(count.get("total_count", 0))
    stations = {}
    for offset in range(0, total_count, PAGE_SIZE):
        page = await _api_get(session, {"select": "id,latitude,longitude,cp,adresse,ville,services,horaires_automate_24_24", "where": where, "offset": offset, "limit": PAGE_SIZE})
        for row in page.get("results", []):
            station_id = str(row.get("id", ""))
            identity = catalog.get(station_id)
            if not identity:
                continue
            try:
                lat = float(row["latitude"]) / 100000
                lon = float(row["longitude"]) / 100000
            except (KeyError, TypeError, ValueError):
                continue
            postal_code = str(row.get("cp") or "").strip()
            if not postal_code:
                continue
            stations[station_id] = {
                "station_id": station_id,
                "name": identity.get("name") or station_id,
                "brand": identity.get("brand", "TotalEnergies"),
                "latitude": lat,
                "longitude": lon,
                "distance_km": round(_distance_km(latitude, longitude, lat, lon), 2),
                "postal_code": postal_code,
                "address": row.get("adresse"),
                "city": row.get("ville"),
                "services": row.get("services", {}),
                "automate_24_24": row.get("horaires_automate_24_24"),
                "fuels": {},
            }
    return stations


async def update_prices(session, stations):
    station_ids = list(stations)
    for offset in range(0, len(station_ids), PAGE_SIZE):
        batch = station_ids[offset:offset + PAGE_SIZE]
        fields = ["id", "rupture", "carburants_disponibles", "carburants_indisponibles", "carburants_rupture_temporaire", "carburants_rupture_definitive"]
        for fuel in FUELS:
            fields += [f"{fuel}_prix", f"{fuel}_maj", f"{fuel}_rupture_type", f"{fuel}_rupture_debut"]
        data = await _api_get(session, {"select": ",".join(fields), "where": _ids_where(batch), "limit": len(batch)})

        for record in data.get("results", []):
            station = stations.get(str(record.get("id")))
            if not station:
                continue
            station_id = str(record.get("id"))
            official_ruptures = _parse_rupture_field(record.get("rupture"))
            available = _parse_names(record.get("carburants_disponibles"))
            unavailable = _parse_names(record.get("carburants_indisponibles"))
            temporary = _parse_names(record.get("carburants_rupture_temporaire"))
            definitive = _parse_names(record.get("carburants_rupture_definitive"))
            fuels = {}
            _LOGGER.debug("Station %s ruptures=%s disponibles=%s indisponibles=%s temporaires=%s definitives=%s", station_id, official_ruptures, available, unavailable, temporary, definitive)

            for key, label in FUELS.items():
                raw_price = record.get(f"{key}_prix")
                updated = record.get(f"{key}_maj")
                rupture_type = record.get(f"{key}_rupture_type")
                rupture_since = record.get(f"{key}_rupture_debut")
                official = official_ruptures.get(key)

                if official:
                    rupture = True
                    rupture_type = official.get("type") or rupture_type or "declaree"
                    rupture_since = official.get("since") or rupture_since
                elif key in unavailable or key in temporary or key in definitive:
                    rupture = True
                elif key in available:
                    rupture = False
                elif rupture_type and _norm(str(rupture_type)) not in INVALID_STATUS:
                    rupture = True
                else:
                    rupture = False

                if rupture_type and _norm(str(rupture_type)) in INVALID_STATUS:
                    rupture_type = None
                try:
                    price = float(raw_price) if raw_price is not None else None
                except (TypeError, ValueError):
                    price = None

                if price is None and not rupture:
                    continue
                if price is None and not rupture_type and not official:
                    continue

                fuels[key] = {
                    "label": label,
                    "price": price,
                    "updated": updated,
                    "rupture": rupture,
                    "rupture_type": rupture_type,
                    "rupture_since": rupture_since,
                }
            station["fuels"] = fuels
    return stations
