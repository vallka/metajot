from metajot.ai import (
    AdobeStockCategory,
    AIResponse,
    ShutterstockCategory,
    build_shutterstock_description,
    resolve_editorial_dateline,
    resolve_location,
)
from metajot.location import Location
from metajot.metadata import ImageMetadata

DESC = "A harbour scene."
EDITORIAL_DESC = "Edinburgh, UK - August 30, 2025: A harbour scene."
EDINBURGH = Location(city="Edinburgh", country="UK")


def _ai_response(**location) -> AIResponse:
    return AIResponse(
        notable_subjects=[],
        notable_details=[],
        setting_and_context="",
        mood_and_style=[],
        title="T",
        description="D",
        keywords=[],
        adobe_category=AdobeStockCategory.TRAVEL,
        shutterstock_category_primary=ShutterstockCategory.NATURE,
        **location,
    )


def test_build_shutterstock_description_plain_when_not_editorial():
    result = build_shutterstock_description(DESC, EDINBURGH, "20250830")
    assert result == DESC


def test_build_shutterstock_description_strips_banned_chars():
    result = build_shutterstock_description("Cats & dogs <playing> indoor/outdoor")
    assert result == "Cats and dogs playing indoor outdoor"


def test_build_shutterstock_description_editorial():
    result = build_shutterstock_description(
        DESC, EDINBURGH, "20250830", editorial=True
    )
    assert result == EDITORIAL_DESC


def test_build_shutterstock_description_falls_back_when_location_missing():
    result = build_shutterstock_description(DESC, None, "20250830", editorial=True)
    assert result == DESC


def test_build_shutterstock_description_falls_back_when_date_missing():
    result = build_shutterstock_description(DESC, EDINBURGH, None, editorial=True)
    assert result == DESC


def test_resolve_location_prefers_embedded_over_ai_guess():
    meta = ImageMetadata(iptc_city="Edinburgh", iptc_country="UK")
    result = resolve_location(meta, Location(city="Paris", country="France"))
    assert result == EDINBURGH


def test_resolve_location_prefers_gps_over_ai_guess():
    meta = ImageMetadata(gps_latitude=55.9533, gps_longitude=-3.1883)
    result = resolve_location(meta, Location(city="Paris", country="France"))
    assert result == EDINBURGH


def test_resolve_location_falls_back_to_ai_guess():
    guess = Location(city="Paris", country="France")
    assert resolve_location(ImageMetadata(), guess) == guess


def test_ai_response_location_guess():
    response = _ai_response(
        location_city="Edinburgh",
        location_province_state="Scotland",
        location_country="UK",
    )
    assert response.location_guess() == Location("Edinburgh", "Scotland", "UK")


def test_ai_response_location_guess_none_when_empty():
    assert _ai_response().location_guess() is None


def test_resolve_editorial_dateline_resolved():
    assert resolve_editorial_dateline(EDINBURGH, "20250830") == (
        "Edinburgh, UK",
        "August 30, 2025",
    )


def test_resolve_editorial_dateline_none_when_location_missing():
    assert resolve_editorial_dateline(None, "20250830") is None


def test_resolve_editorial_dateline_none_when_date_missing():
    assert resolve_editorial_dateline(EDINBURGH, None) is None
