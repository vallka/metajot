from fotoai.location import (
    build_editorial_description,
    format_editorial_date,
    format_editorial_location,
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


def test_format_editorial_location_us_uses_state_abbreviation():
    city = reverse_geocode(40.7128, -74.0060)
    assert format_editorial_location(city) == "New York City, NY"


def test_format_editorial_location_non_us_uses_country_name():
    city = reverse_geocode(55.9533, -3.1883)
    assert format_editorial_location(city) == "Edinburgh, UK"


def test_format_editorial_date():
    assert format_editorial_date("20250830") == "August 30, 2025"


def test_format_editorial_date_invalid_returns_none():
    assert format_editorial_date("not-a-date") is None


def test_build_editorial_description():
    result = build_editorial_description(
        "Edinburgh, UK", "August 30, 2025", "A harbour scene."
    )
    assert result == "Edinburgh, UK - August 30, 2025: A harbour scene."
