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

# Keep the TotalEnergies network only. The government station catalogue contains
# the FR:prix-carburants reference used to join the two datasets.
TOTAL_BRANDS = {
    "total",
    "total energies",
    "totalenergies",
    "total access",
    "totalaccess",
    "total contact",
    "totalcontact",
    "totalenergies access",
    "total energies access",
}

FUELS = {
    "gazole": "Gazole",
    "sp95": "SP95",
    "sp98": "SP98",
    "e10": "E10",
    "e85": "E85",
    "gplc": "GPLc",
}

# These values are not actionable fuel statuses. A fuel carrying one of these
# values is deliberately omitted from Home Assistant instead of being shown as
# available or in rupture.
INVALID_STATUS = {
    "",
    "inconnu",
    "unknown",
    "inconue",
    "probleme",
    "problem",
    "erreur",
    "error",
    "undefined",
    "null",
}


def _norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(value.lower().replace("-", " ").split())


def _fuel_key(value: str | None) -> str | None:
    aliases = {
        "gazole": "gazole",
        "diesel": "gazole",
        "diesel premier": "gazole",
        "gazole premier": "gazole",
        "sp95": "sp95",
        "sans plomb 95": "sp95",
        "sp95 e10": "e10",
        "sp95 e 10": "e10",
        "sans plomb e10": "e10",
        "sans plomb 95 e10": "e10",
        "e10": "e10",
        "sp98": "sp98",
        "sans plomb 98": "sp98",
        "excellium sp98": "sp98",
        "e85": "e85",
        "superethanol e85": "e85",
        "gplc": "gplc",
        "gpl": "gplc",
        "lpg": "gplc",
    }
    return aliases.get(_norm(value))


def _is_total(*values: str | None) -> bool:
    return any(_norm(v) in TOTAL_BRANDS for v in values if v)


def _parse_names(value) -> set[str]:
    """Parse the semicolon-separated fuel lists from the v2 dataset."""
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

    result: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            item = item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel") or ""
        key = _fuel_key(str(item))
        if key:
            result.add(key)
    return result


def _parse_rupture_field(raw) -> dict[str, dict]:
    """Parse the official `rupture` JSON field."""
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

    result: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = _fuel_key(
            item.get("@nom") or item.get("nom") or item.get("name") or item.get("fuel")
        )
        if not key:
            continue
        rupture_type = item.get("@type") or item.get("type")
        rupture_type = None if _norm(rupture_type) in INVALID_STATUS else rupture_type
        result[key] = {
            "type": rupture_type,
            "since": item.get("@debut") or item.get("debut"),
            "end": item.get("@fin") or item.get("fin"),
        }
    return result


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(p1) * cos(p2) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _parse_coordinates(row: dict) -> tuple[float, float] | None:
    """Use geom when present, otherwise the legacy scaled lat/lon fields."""
    geom = row.get("geom")
    if isinstance(geom, dict):
        geom = geom.get("coordinates")
    if isinstance(geom, (list, tuple)) and len(geom) >= 2:
        try:
            # ODS geo_point is [latitude, longitude] in the dataset response.
            return float(geom[0]), float(geom[1])
        except (TypeError, ValueError):
            pass

    try:
        lat = float(row["latitude"]) / 100000
        lon = float(row["longitude"]) / 100000
        return lat, lon
    except (KeyError, TypeError, ValueError):
        return None


def parse_catalog(raw: bytes) -> dict[str, dict[str, str]]:
    """Read stations-service-1 and retain only TotalEnergies network stations."""
    text = bz2.decompress(raw).decode("utf-8-sig")
    result: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        raw_ids = (
            row.get("ref:FR:prix-carburants")
            or row.get("ref:FR:PrixCarburants")
            or ""
        ).strip()
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
            station_id = station_id.strip()
            if station_id:
                result.setdefault(
                    station_id,
                    {"name": name, "brand": network_name},
                )
    return result


async def fetch_total_catalog(session: aiohttp.ClientSession):
    async with session.get(STATIONS_CATALOG_URL) as response:
        response.raise_for_status()
        catalog = parse_catalog(await response.read())
    if not catalog:
        raise RuntimeError("Aucune station Total trouvée dans stations-service-1")
    _LOGGER.debug("Catalogue stations-service : %s stations Total", len(catalog))
    return catalog


async def _api_get(session: aiohttp.ClientSession, params: dict) -> dict:
    async with session.get(
        PRICE_API_URL,
        params=params,
        headers={"Accept": "application/json"},
    ) as response:
        if response.status >= 400:
            body = await response.text()
            raise RuntimeError(
                f"API carburants HTTP {response.status}: {body[:500]}"
            )
        return await response.json()


def _nearby_where(latitude: float, longitude: float, radius_km: float) -> str:
    # v2.1 uses within_distance() in WHERE. The old distance() form was a
    # common source of HTTP 400 errors after the v2.1 migration.
    return (
        f"within_distance(geom, geom'POINT({longitude} {latitude})', "
        f"{radius_km} km)"
    )


async def fetch_nearby_total_stations(
    session,
    catalog: dict[str, dict[str, str]],
    latitude: float,
    longitude: float,
    radius_km: float,
):
    """Find nearby stations in the official price dataset, then join to the Total catalogue."""
    where = _nearby_where(latitude, longitude, radius_km)
    stations: dict[str, dict] = {}

    # No count endpoint is needed: page until a short page is returned.
    offset = 0
    while True:
        page = await _api_get(
            session,
            {
                "select": "id,latitude,longitude,geom,cp,adresse,ville,services,horaires_automate_24_24",
                "where": where,
                "offset": offset,
                "limit": PAGE_SIZE,
            },
        )
        rows = page.get("results", [])
        if not rows:
            break

        for row in rows:
            station_id = str(row.get("id", "")).strip()
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

            stations[station_id] = {
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
                "fuels": {},
            }

        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    _LOGGER.debug("%s stations Total trouvées dans %.1f km", len(stations), radius_km)
    return stations


def _field_is_invalid(value) -> bool:
    return value is not None and _norm(str(value)) in INVALID_STATUS


def _fuel_value(record: dict, key: str) -> dict | None:
    """Build one fuel state from the official rupture/availability fields."""
    raw_price = record.get(f"{key}_prix")
    updated = record.get(f"{key}_maj")
    rupture_type = record.get(f"{key}_rupture_type")
    rupture_since = record.get(f"{key}_rupture_debut")

    # Explicit invalid status means: do not expose this fuel at all.
    if _field_is_invalid(rupture_type):
        return None

    try:
        price = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        price = None

    if price is None and not rupture_type:
        return None

    return {
        "label": FUELS[key],
        "price": price,
        "updated": updated,
        "rupture": False,
        "rupture_type": rupture_type,
        "rupture_since": rupture_since,
    }


async def update_prices(session, stations):
    """Refresh prices and official rupture flags for the already filtered Total stations."""
    station_ids = list(stations)
    if not station_ids:
        return stations

    for offset in range(0, len(station_ids), PAGE_SIZE):
        batch = station_ids[offset : offset + PAGE_SIZE]

        # IDs are integers in the v2 dataset. Never quote them in the IN clause:
        # `id IN ("42510003")` produces HTTP 400 from ODS v2.1.
        numeric_ids = []
        for station_id in batch:
            try:
                numeric_ids.append(str(int(station_id)))
            except (TypeError, ValueError):
                continue
        if not numeric_ids:
            continue

        data = await _api_get(
            session,
            {
                "select": (
                    "id,rupture,carburants_disponibles,carburants_indisponibles,"
                    "carburants_rupture_temporaire,carburants_rupture_definitive,"
                    "gazole_prix,gazole_maj,gazole_rupture_type,gazole_rupture_debut,"
                    "sp95_prix,sp95_maj,sp95_rupture_type,sp95_rupture_debut,"
                    "sp98_prix,sp98_maj,sp98_rupture_type,sp98_rupture_debut,"
                    "e10_prix,e10_maj,e10_rupture_type,e10_rupture_debut,"
                    "e85_prix,e85_maj,e85_rupture_type,e85_rupture_debut,"
                    "gplc_prix,gplc_maj,gplc_rupture_type,gplc_rupture_debut"
                ),
                "where": f"id IN ({','.join(numeric_ids)})",
                "limit": len(numeric_ids),
            },
        )

        found_ids: set[str] = set()
        for record in data.get("results", []):
            station_id = str(record.get("id", "")).strip()
            station = stations.get(station_id)
            if not station:
                continue
            found_ids.add(station_id)

            official_ruptures = _parse_rupture_field(record.get("rupture"))
            available = _parse_names(record.get("carburants_disponibles"))
            unavailable = _parse_names(record.get("carburants_indisponibles"))
            temporary = _parse_names(record.get("carburants_rupture_temporaire"))
            definitive = _parse_names(record.get("carburants_rupture_definitive"))
            fuels: dict[str, dict] = {}

            for key in FUELS:
                value = _fuel_value(record, key)
                if value is None:
                    continue

                official = official_ruptures.get(key)
                if official:
                    # The official `rupture` field wins over the price/available
                    # fields. This is the important fix for stations such as Feurs.
                    value["rupture"] = True
                    value["rupture_type"] = official.get("type") or value.get("rupture_type")
                    value["rupture_since"] = official.get("since") or value.get("rupture_since")
                elif key in unavailable or key in temporary or key in definitive:
                    value["rupture"] = True
                    if key in definitive:
                        value["rupture_type"] = "definitive"
                    elif key in temporary:
                        value["rupture_type"] = "temporaire"
                elif key in available:
                    value["rupture"] = False
                elif value.get("rupture_type"):
                    value["rupture"] = True

                # A bad/unknown rupture status must never become a visible fuel.
                if _field_is_invalid(value.get("rupture_type")):
                    continue

                fuels[key] = value

            station["fuels"] = fuels
            _LOGGER.debug(
                "Station %s: ruptures=%s disponibles=%s indisponibles=%s temporaires=%s definitives=%s",
                station_id,
                list(official_ruptures),
                sorted(available),
                sorted(unavailable),
                sorted(temporary),
                sorted(definitive),
            )

        # If the API silently omits a station, do not erase its last known data.
        missing = set(batch) - found_ids
        if missing:
            _LOGGER.warning("Stations Total absentes de la réponse prix : %s", sorted(missing))

    return stations
