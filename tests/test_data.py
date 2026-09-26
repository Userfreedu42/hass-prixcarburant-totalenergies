import bz2
import importlib.util
import json
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "prix_carburant_totalenergies" / "data.py"
_SPEC = importlib.util.spec_from_file_location("total_data", _MODULE_PATH)
_data = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_data)


def test_fuel_aliases():
    assert _data._fuel_key("Excellium SP98") == "sp98"
    assert _data._fuel_key("Diesel Premier") == "gazole"
    assert _data._fuel_key("SP95-E10") == "e10"
    assert _data._fuel_key("GPL") == "gplc"


def test_parse_names():
    assert _data._parse_names("Gazole;E10;SP98") == {"gazole", "e10", "sp98"}


def test_parse_official_ruptures():
    raw = json.dumps([
        {"@nom": "Gazole", "@type": "definitive", "@debut": "2026-09-25"},
        {"@nom": "E10", "@type": "temporaire"},
    ])
    parsed = _data._parse_rupture_field(raw)
    assert parsed["gazole"]["type"] == "definitive"
    assert parsed["e10"]["type"] == "temporaire"


def test_v21_geo_filter():
    where = _data._nearby_where(45.82, 4.1, 15)
    assert where == "within_distance(geom, geom'POINT(4.1 45.82)', 15 km)"
    assert "distance(geom, geom'" not in where


def test_catalog_keeps_total_and_discards_other_brands():
    csv_data = (
        "ref:FR:prix-carburants,brand,operator,branch,name\n"
        "42110006,Total,,,RELAIS DE FEURS\n"
        "42110003,Intermarche,,,INTERMARCHE FEURS\n"
        "42510003,Total,,,A-DR PASSION\n"
    ).encode("utf-8")
    catalog = _data.parse_catalog(bz2.compress(csv_data))
    assert "42110006" in catalog
    assert "42510003" in catalog
    assert "42110003" not in catalog
