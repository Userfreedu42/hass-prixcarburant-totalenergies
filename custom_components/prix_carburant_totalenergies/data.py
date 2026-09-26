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

TOTAL_BRANDS = {
    "total", "total energies", "totalenergies", "total access", "totalaccess",
    "total contact", "totalcontact", "totalenergies access", "total energies access",
}

FUELS = {
    "gazole": "Gazole",
    "sp95": "SP95",
    "sp98": "SP98",
    "e10": "E10",
    "e85": "E85",
    "gplc": "GPLc",
}

INVALID_STATUS = {"", "inconnu", "unknown", "inconue", "probleme", "problem", "erreur", "error", "undefined", "null"}


def _norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(value.lower().replace("-", " ").split())


def _station_key(value) -> str:
    """Canonicalise a station id so 042110001 and 42110001 match the API integer id."""
    text = str(value or "").strip()
    try:
        return str(int(text))
    except (TypeError, ValueError):
        return text


def _fuel_key(value: str | None) -> str | None:
    aliases = {
        "gazole": "gazole", "diesel": "gazole", "diesel premier": "gazole", "gazole premier": "gazole",
        "sp95": "sp95", "sans plomb 95": "sp95",
        "sp95 e10": "e10", "sp95 e 10": "e10", "sans plomb e10": "e10", "sans plomb 95 e10": "e10", "e10": "e10",
        "sp98": "sp98", "sans plomb 98": "sp98", "excellium sp98": "sp98",
        "e85": "e85", "superethanol e85": "e85", "super ethanol e85": "e85",
        "gplc": "gplc", "gpl": "gplc", "lpg": "gplc",
    }
    return aliases.get(_norm(value))


def _is_total(*values: str | None) -> bool:
    return any(_norm(v) in TOTAL_BRANDS for v in values if v)


def _parse_json_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if any(k in value for k in ("@nom", "nom", "name", "fuel")):
            return [value]
        return [{"@nom": key, **(item if isinstance(item, dict) else {"value": item})} for key, item in value.items()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return _parse_json_list(parsed)
    return []


def _parse_names(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return set()
        parsed = _parse_json_list(text)
        items = parsed if parsed else text.replace("\n", ";").replace(",", ";").split(";")
    elif isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = list(value.keys())
    else:
        items = [value]
    result = set()
    for item in items:
        if isinstance(item, dict):
            item = item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel") or ""
        key = _fuel_key(str(item))
        if key:
            result.add(key)
    return result


def _parse_prices(value) -> dict[str, dict]:
    result = {}
    for item in _parse_json_list(value):
        if not isinstance(item, dict):
            continue
        key = _fuel_key(item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel"))
        if not key:
            continue
        raw = item.get("@valeur") or item.get("valeur") or item.get("price") or item.get("value")
        try:
            price = float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        result[key] = {
            "price": price,
            "updated": item.get("@maj") or item.get("maj") or item.get("updated"),
        }
    return result


def _parse_rupture_field(raw) -> dict[str, dict]:
    result = {}
    for item in _parse_json_list(raw):
        if not isinstance(item, dict):
            continue
        key = _fuel_key(item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel"))
        if not key:
            continue
        rupture_type = item.get("@type") or item.get("type")
        if _norm(rupture_type) in INVALID_STATUS:
            rupture_type = None
        result[key] = {
            "type": rupture_type,
            "since": item.get("@debut") or item.get("debut"),
            "end": item.get("@fin") or item.get("fin"),
        }
    return result


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(p1) * cos(p2) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _parse_coordinates(row: dict) -> tuple[float, float] | None:
    geom = row.get("geom")
    if isinstance(geom, dict):
        geom = geom.get("coordinates")
    if isinstance(geom, (list, tuple)) and len(geom) >= 2:
        try:
            return float(geom[0]), float(geom[1])
        except (TypeError, ValueError):
            pass
    try:
        return float(row["latitude"]) / 100000, float(row["longitude"]) / 100000
    except (KeyError, TypeError, ValueError):
        return None


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
        network_name = brand or operator or branch or "TotalEnergies"
        for station_id in raw_ids.split(";"):
            key = _station_key(station_id)
            if key:
                result.setdefault(key, {"name": name, "brand": network_name})
    return result


async def fetch_total_catalog(session: aiohttp.ClientSession):
    async with session.get(STATIONS_CATALOG_URL) as response:
        response.raise_for_status()
        catalog = parse_catalog(await response.read())
    if not catalog:
        raise RuntimeError("Aucune station Total trouvée dans stations-service-1")
    return catalog


async def _api_get(session: aiohttp.ClientSession, params: dict) -> dict:
    async with session.get(PRICE_API_URL, params=params, headers={"Accept": "application/json"}) as response:
        if response.status >= 400:
            body = await response.text()
            raise RuntimeError(f"API carburants HTTP {response.status}: {body[:500]}")
        return await response.json()


def _nearby_where(latitude: float, longitude: float, radius_km: float) -> str:
    return f"within_distance(geom, geom'POINT({longitude} {latitude})', {radius_km} km)"


def _fuel_record(record: dict) -> dict[str, dict]:
    """Build visible fuels from the official v2 record.

    `prix` and `rupture` are the canonical JSON fields documented by the
    government dataset; the *_prix/*_rupture_* columns are used as fallbacks.
    """
    generic_prices = _parse_prices(record.get("prix"))
    official_ruptures = _parse_rupture_field(record.get("rupture"))
    available = _parse_names(record.get("carburants_disponibles"))
    unavailable = _parse_names(record.get("carburants_indisponibles"))
    temporary = _parse_names(record.get("carburants_rupture_temporaire"))
    definitive = _parse_names(record.get("carburants_rupture_definitive"))
    fuels = {}

    for key, label in FUELS.items():
        raw_price = record.get(f"{key}_prix")
        updated = record.get(f"{key}_maj")
        if raw_price in (None, "") and key in generic_prices:
            raw_price = generic_prices[key].get("price")
            updated = generic_prices[key].get("updated") or updated
        try:
            price = float(raw_price) if raw_price not in (None, "") else None
        except (TypeError, ValueError):
            price = None

        rupture_type = record.get(f"{key}_rupture_type")
        rupture_since = record.get(f"{key}_rupture_debut")
        official = official_ruptures.get(key)

        if official is not None:
            rupture = True
            rupture_type = official.get("type") or rupture_type or "declaree"
            rupture_since = official.get("since") or rupture_since
        elif key in definitive:
            rupture = True
            rupture_type = "definitive"
        elif key in temporary:
            rupture = True
            rupture_type = "temporaire"
        elif key in unavailable:
            rupture = True
            if not rupture_type or _norm(rupture_type) in INVALID_STATUS:
                rupture_type = "declaree"
        elif rupture_type and _norm(rupture_type) not in INVALID_STATUS:
            rupture = True
        else:
            rupture = False

        # A listed price or availability/rupture entry means the fuel exists.
        # We never create a sensor for a genuinely unknown fuel.
        has_data = (
            key in generic_prices or price is not None or key in available
            or key in unavailable or key in temporary or key in definitive
            or official is not None
        )
        if not has_data:
            continue

        if rupture_type and _norm(rupture_type) in INVALID_STATUS:
            rupture_type = None

        fuels[key] = {
            "label": label,
            "price": price,
            "updated": updated,
            "rupture": rupture,
            "rupture_type": rupture_type,
            "rupture_since": rupture_since,
        }
    return fuels


async def fetch_nearby_total_stations(session, catalog, latitude, longitude, radius_km):
    where = _nearby_where(latitude, longitude, radius_km)
    stations = {}
    offset = 0
    select = (
        "id,latitude,longitude,geom,cp,adresse,ville,services,horaires_automate_24_24,"
        "prix,rupture,carburants_disponibles,carburants_indisponibles,"
        "carburants_rupture_temporaire,carburants_rupture_definitive,"
        "gazole_prix,gazole_maj,gazole_rupture_type,gazole_rupture_debut,"
        "sp95_prix,sp95_maj,sp95_rupture_type,sp95_rupture_debut,"
        "sp98_prix,sp98_maj,sp98_rupture_type,sp98_rupture_debut,"
        "e10_prix,e10_maj,e10_rupture_type,e10_rupture_debut,"
        "e85_prix,e85_maj,e85_rupture_type,e85_rupture_debut,"
        "gplc_prix,gplc_maj,gplc_rupture_type,gplc_rupture_debut"
    )

    while True:
        page = await _api_get(session, {"select": select, "where": where, "offset": offset, "limit": PAGE_SIZE})
        rows = page.get("results", [])
        if not rows:
            break

        for row in rows:
            station_id = _station_key(row.get("id"))
            identity = catalog.get(station_id)
            if not identity:
                continue
            coordinates = _parse_coordinates(row)
            if not coordinates:
                continue
            lat, lon = coordinates
            postal_code = str(row.get("cp") or "").strip()
            city = str(row.get("ville") or "").strip()
            if not postal_code or not city:
                continue

            station = {
                "station_id": station_id,
                "name": identity.get("name") or station_id,
                "brand": identity.get("brand", "TotalEnergies"),
                "latitude": lat,
                "longitude": lon,
                "distance_km": round(_distance_km(latitude, longitude, lat, lon), 2),
                "postal_code": postal_code,
                "address": row.get("adresse"),
                "city": city,
                "services": row.get("services", {}),
                "automate_24_24": row.get("horaires_automate_24_24"),
                "fuels": _fuel_record(row),
            }
            stations[station_id] = station

        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    _LOGGER.debug("%s stations Total trouvées, dont %s avec carburants", len(stations), sum(bool(s["fuels"]) for s in stations.values()))
    return stations


async def update_prices(session, stations):
    """Refresh fuel data while keeping station ids canonical.

    This second pass is deliberately independent from the station discovery
    query. It also uses the same canonical integer station id on both sides,
    which prevents a leading-zero station id from producing an empty `fuels` map.
    """
    station_ids = list(stations)
    if not station_ids:
        return stations

    select = (
        "id,prix,rupture,carburants_disponibles,carburants_indisponibles,"
        "carburants_rupture_temporaire,carburants_rupture_definitive,"
        "gazole_prix,gazole_maj,gazole_rupture_type,gazole_rupture_debut,"
        "sp95_prix,sp95_maj,sp95_rupture_type,sp95_rupture_debut,"
        "sp98_prix,sp98_maj,sp98_rupture_type,sp98_rupture_debut,"
        "e10_prix,e10_maj,e10_rupture_type,e10_rupture_debut,"
        "e85_prix,e85_maj,e85_rupture_type,e85_rupture_debut,"
        "gplc_prix,gplc_maj,gplc_rupture_type,gplc_rupture_debut"
    )

    for offset in range(0, len(station_ids), PAGE_SIZE):
        batch = station_ids[offset:offset + PAGE_SIZE]
        ids = [_station_key(value) for value in batch if _station_key(value)]
        if not ids:
            continue
        data = await _api_get(session, {
            "select": select,
            "where": f"id IN ({','.join(ids)})",
            "limit": len(ids),
        })

        matched = 0
        for record in data.get("results", []):
            station = stations.get(_station_key(record.get("id")))
            if station is None:
                continue
            station["fuels"] = _fuel_record(record)
            matched += 1

        if matched != len(ids):
            _LOGGER.warning("Prix carburants: %s/%s stations reçues par l'API", matched, len(ids))

    return stations
