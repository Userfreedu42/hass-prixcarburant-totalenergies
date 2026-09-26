import json

from custom_components.prix_carburant_totalenergies.data import (
    _nearby_where,
    _parse_rupture_field,
    _parse_names,
    _fuel_key,
    parse_catalog,
)


def test_fuel_aliases():
    assert _fuel_key("Excellium SP98") == "sp98"
    assert _fuel_key("Diesel Premier") == "gazole"
    assert _fuel_key("SP95-E10") == "e10"
    assert _fuel_key("GPL") == "gplc"


def test_parse_names():
    assert _parse_names("Gazole;E10;SP98") == {"gazole", "e10", "sp98"}


def test_parse_official_ruptures():
    raw = json.dumps([
        {"@nom": "Gazole", "@type": "definitive", "@debut": "2026-09-25"},
        {"@nom": "E10", "@type": "temporaire"},
    ])
    parsed = _parse_rupture_field(raw)
    assert parsed["gazole"]["type"] == "definitive"
    assert parsed["e10"]["type"] == "temporaire"


def test_v21_geo_filter():
    where = _nearby_where(45.82, 4.1, 15)
    assert where == "within_distance(geom, geom'POINT(4.1 45.82)', 15 km)"
    assert "distance(geom, geom'" not in where


def test_catalog_keeps_total_and_discards_other_brands():
    import bz2
    import io

    csv_data = (
        "ref:FR:prix-carburants,brand,operator,branch,name\n"
        "42110006,Total,,,RELAIS DE FEURS\n"
        "42110003,Intermarche,,,INTERMARCHE FEURS\n"
        "42510003,Total,, ,A-DR PASSION\n"
    ).encode("utf-8")
    raw = bz2.compress(csv_data)
    catalog = parse_catalog(raw)
    assert "42110006" in catalog
    assert "42510003" in catalog
    assert "42110003" not in catalog
