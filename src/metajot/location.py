"""Offline reverse geocoding and AP/Reuters-style editorial dateline
formatting ("City, State/Country - Month Day Year").

Turning GPS coordinates into a city name needs a real deterministic lookup,
not a vision model guessing at raw lat/long numbers, so this module ships a
small GeoNames-derived dataset (src/metajot/data/cities.tsv,
src/metajot/data/countries.tsv - see data/ATTRIBUTION.txt) and does simple
nearest-neighbour matching in pure Python: no network calls, no extra
heavyweight dependencies (numpy/scipy).
"""

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).parent / "data"
CITIES_PATH = DATA_DIR / "cities.tsv"
COUNTRIES_PATH = DATA_DIR / "countries.tsv"

EARTH_RADIUS_KM = 6371.0

# Editorial-style short forms for countries that are conventionally
# abbreviated in datelines rather than spelled out in full.
COUNTRY_NAME_OVERRIDES = {"GB": "UK"}

# Spellings of the US country name (from GeoNames, existing IPTC fields, or
# the AI) that mean the dateline should use the state instead of the country.
US_COUNTRY_NAMES = {
    "us",
    "usa",
    "u.s.",
    "u.s.a.",
    "united states",
    "united states of america",
}


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    country_code: str
    admin1_code: str
    population: int


@dataclass
class Location:
    """A photo's location, as stored in the IPTC City / Province-State /
    Country fields (mirrored to XMP photoshop:City/State/Country)."""

    city: Optional[str] = None
    province_state: Optional[str] = None
    country: Optional[str] = None

    def is_empty(self) -> bool:
        return not (self.city or self.province_state or self.country)


def _grid_key(lat: float, lon: float) -> Tuple[int, int]:
    return (int(math.floor(lat)), int(math.floor(lon)))


@lru_cache(maxsize=1)
def _load_cities() -> List[City]:
    cities = []
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        for name, lat, lon, country_code, admin1_code, population in csv.reader(
            f, delimiter="\t"
        ):
            cities.append(
                City(
                    name=name,
                    lat=float(lat),
                    lon=float(lon),
                    country_code=country_code,
                    admin1_code=admin1_code,
                    population=int(population) if population else 0,
                )
            )
    return cities


@lru_cache(maxsize=1)
def _load_city_grid() -> Dict[Tuple[int, int], List[int]]:
    grid: Dict[Tuple[int, int], List[int]] = {}
    for index, city in enumerate(_load_cities()):
        grid.setdefault(_grid_key(city.lat, city.lon), []).append(index)
    return grid


@lru_cache(maxsize=1)
def _load_countries() -> Dict[str, str]:
    countries = {}
    with open(COUNTRIES_PATH, "r", encoding="utf-8") as f:
        for country_code, country_name in csv.reader(f, delimiter="\t"):
            countries[country_code] = country_name
    return countries


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(
        d_lambda / 2
    ) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def reverse_geocode(
    lat: float, lon: float, max_radius_cells: int = 12
) -> Optional[City]:
    """Returns the nearest known city to (lat, lon), or None if nothing is
    found within max_radius_cells degree-sized grid cells (covers all but
    the most remote open-ocean/polar coordinates)."""
    cities = _load_cities()
    grid = _load_city_grid()
    base_row, base_col = _grid_key(lat, lon)

    best_city: Optional[City] = None
    best_distance = math.inf

    for radius in range(0, max_radius_cells + 1):
        candidate_indices: List[int] = []
        for row in range(base_row - radius, base_row + radius + 1):
            for col in range(base_col - radius, base_col + radius + 1):
                # Only scan the newly-added outer ring each time, not cells
                # already covered by a smaller radius.
                in_inner_ring = (
                    abs(row - base_row) < radius and abs(col - base_col) < radius
                )
                if radius > 0 and in_inner_ring:
                    continue
                candidate_indices.extend(grid.get((row, col), []))

        for index in candidate_indices:
            city = cities[index]
            distance = _haversine_km(lat, lon, city.lat, city.lon)
            if distance < best_distance:
                best_distance = distance
                best_city = city

        # Once we have a match, one extra ring is enough to catch a closer
        # city just across a grid boundary; no need to keep expanding.
        if best_city is not None and radius > 0:
            break

    return best_city


def country_name(country_code: str) -> Optional[str]:
    if country_code in COUNTRY_NAME_OVERRIDES:
        return COUNTRY_NAME_OVERRIDES[country_code]
    return _load_countries().get(country_code)


def location_from_city(city: City) -> Location:
    """Converts a reverse-geocoded City to a Location. Only US cities get a
    province/state, since GeoNames' US admin1 codes are already the USPS
    abbreviation, while elsewhere they're opaque numeric codes."""
    if city.country_code == "US":
        return Location(
            city=city.name,
            province_state=city.admin1_code or None,
            country=country_name("US"),
        )
    return Location(
        city=city.name,
        country=country_name(city.country_code) or city.country_code,
    )


def _is_us(country: Optional[str]) -> bool:
    return bool(country) and country.strip().lower() in US_COUNTRY_NAMES


def format_editorial_location(location: Location) -> Optional[str]:
    """Formats a Location as the "City, State/Country" half of an editorial
    dateline: US locations use the state, everywhere else uses the country
    (or the province/state if no country is known). Without a city, falls
    back to whatever region/country is known, or None if nothing is."""
    if not location.city:
        region_parts = [p for p in (location.province_state, location.country) if p]
        return ", ".join(region_parts) or None

    if _is_us(location.country) and location.province_state:
        region = location.province_state
    else:
        region = location.country or location.province_state
    return f"{location.city}, {region}" if region else location.city


def format_editorial_date(date_created: str) -> Optional[str]:
    """Formats an IPTC "date created" value (CCYYMMDD) as "Month Day, Year"."""
    try:
        dt = datetime.strptime(date_created.strip(), "%Y%m%d")
    except ValueError:
        return None
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def build_editorial_description(
    location_text: str, date_text: str, description: str
) -> str:
    """Assembles the AP/Reuters-style editorial description Shutterstock's
    Editorial content requires: "City, State/Country - Month Day Year:
    Description"."""
    return f"{location_text} - {date_text}: {description}"
