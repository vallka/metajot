from metajot.location import (
    Location,
    build_editorial_description,
    format_editorial_date,
    format_editorial_location,
    location_from_city,
    reverse_geocode,
)


def test_reverse_geocode_finds_edinburgh():
    city = reverse_geocode(55.9533, -3.1883)
    assert city is not None
    assert city.name == "Edinburgh"
    assert city.country_code == "GB"


def test_reverse_geocode_finds_new_york():
    city = reverse_geocode(40.7128, -74.0060)
    assert city is not None
    assert city.country_code == "US"
    assert city.admin1_code == "NY"


def test_reverse_geocode_returns_none_for_remote_ocean_point():
    # Middle of the South Pacific, far from any city in the dataset.
    assert reverse_geocode(0.0, -140.0) is None


def test_location_from_city_us_keeps_state_abbreviation():
    location = location_from_city(reverse_geocode(40.7128, -74.0060))
    assert location.city == "New York City"
    assert location.province_state == "NY"
    assert format_editorial_location(location) == "New York City, NY"


def test_location_from_city_non_us_uses_country_name():
    location = location_from_city(reverse_geocode(55.9533, -3.1883))
    assert location == Location(city="Edinburgh", country="UK")
    assert format_editorial_location(location) == "Edinburgh, UK"


def test_format_editorial_location_non_us_prefers_country_over_state():
    location = Location(city="Edinburgh", province_state="Scotland", country="UK")
    assert format_editorial_location(location) == "Edinburgh, UK"


def test_format_editorial_location_us_spellings_use_state():
    for country in ("USA", "United States", "U.S."):
        location = Location(city="Austin", province_state="TX", country=country)
        assert format_editorial_location(location) == "Austin, TX"


def test_format_editorial_location_uses_state_when_no_country():
    location = Location(city="Edinburgh", province_state="Scotland")
    assert format_editorial_location(location) == "Edinburgh, Scotland"


def test_format_editorial_location_without_city():
    location = Location(province_state="Scotland", country="UK")
    assert format_editorial_location(location) == "Scotland, UK"
    assert format_editorial_location(Location()) is None


def test_format_editorial_date():
    assert format_editorial_date("20250830") == "August 30, 2025"


def test_format_editorial_date_invalid_returns_none():
    assert format_editorial_date("not-a-date") is None


def test_build_editorial_description():
    result = build_editorial_description(
        "Edinburgh, UK", "August 30, 2025", "A harbour scene."
    )
    assert result == "Edinburgh, UK - August 30, 2025: A harbour scene."
