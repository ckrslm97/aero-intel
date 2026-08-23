"""Bundled geographic reference data: every IATA airport a wire service is
likely to name, and every country's world-region slug.

`airports.json` and `countries.json` are **generated** -- regenerate them with
`python scripts/build_airports.py`, which documents the source (OurAirports,
public domain) and the filter applied. Do not hand-edit them; hand-curated
exceptions belong in `app/llm/gazetteer.py`, which layers its own overlay on
top of what is loaded here.

JSON rather than a generated Python module. The airport table is ~800KB either
way, but as a `.py` it would be a dict literal that the interpreter has to
*compile* on every cold start where `__pycache__` is not writable -- which is
exactly the Vercel serverless case this backend deploys to -- and it would sit
in the import graph even for requests that never touch a gazetteer. As JSON it
is parsed by the C `json` module in a few milliseconds, and only when something
first asks for it: every accessor below is `functools.cache`d, so a process
that never resolves an airport never pays for the file at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Airport:
    iata: str
    name: str
    city: str
    country: str  # ISO alpha-2
    lat: float
    lon: float


@cache
def _airports_file() -> dict:
    with (_DATA_DIR / "airports.json").open(encoding="utf-8") as handle:
        return json.load(handle)


@cache
def _countries_file() -> dict[str, dict[str, str]]:
    with (_DATA_DIR / "countries.json").open(encoding="utf-8") as handle:
        return json.load(handle)


@cache
def airports_by_iata() -> dict[str, Airport]:
    return {
        row["iata"]: Airport(
            iata=row["iata"],
            name=row["name"],
            city=row["city"],
            country=row["country"],
            lat=row["lat"],
            lon=row["lon"],
        )
        for row in _airports_file()["airports"]
    }


@cache
def airport_aliases() -> dict[str, str]:
    """Match alias -> IATA code. Keys are already folded into the matcher's
    normalised space (see `app.llm.gazetteer.fold_for_match`) by the build
    script; they are not display strings."""
    return _airports_file()["aliases"]


def airport(code: str | None) -> Airport | None:
    if not code:
        return None
    return airports_by_iata().get(code.upper())


@cache
def country_names() -> dict[str, str]:
    """ISO alpha-2 -> country name, lowercased to match the gazetteer's
    `COUNTRIES` keys and `app.taxonomy.COUNTRY_TO_REGION`."""
    return {iso: entry["name"] for iso, entry in _countries_file().items()}


@cache
def country_regions_by_name() -> dict[str, str]:
    """Lowercase country name -> world-region slug. The generated half of
    `app.taxonomy.COUNTRY_TO_REGION`."""
    return {entry["name"]: entry["region"] for entry in _countries_file().values()}


def country_name(iso: str | None) -> str | None:
    if not iso:
        return None
    return country_names().get(iso.upper())
