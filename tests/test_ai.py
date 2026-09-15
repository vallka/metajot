from fotoai.ai import (
    build_shutterstock_description,
    resolve_editorial_dateline,
    resolve_editorial_location,
)
from fotoai.metadata import ImageMetadata

DESC = "A harbour scene."
EDITORIAL_DESC = "Edinburgh, UK - August 30, 2025: A harbour scene."


def test_build_shutterstock_description_plain_when_not_editorial():
    meta = ImageMetadata(
        iptc_city="Edinburgh", iptc_country="UK", date_created="20250830"
    )
    result = build_shutterstock_description(meta, DESC, editorial=False)
    assert result == DESC


def test_build_shutterstock_description_strips_banned_chars():
    meta = ImageMetadata()
    result = build_shutterstock_description(
        meta, "Cats & dogs <playing> indoor/outdoor", editorial=False
    )
    assert result == "Cats and dogs playing indoor outdoor"


def test_build_shutterstock_description_editorial_uses_iptc_location():
    meta = ImageMetadata(
        iptc_city="Edinburgh", iptc_country="UK", date_created="20250830"
    )
    result = build_shutterstock_description(meta, DESC, editorial=True)
    assert result == EDITORIAL_DESC


def test_build_shutterstock_description_editorial_uses_gps_when_no_iptc_location():
    meta = ImageMetadata(
        gps_latitude=55.9533, gps_longitude=-3.1883, date_created="20250830"
    )
    result = build_shutterstock_description(meta, DESC, editorial=True)
    assert result == EDITORIAL_DESC


def test_build_shutterstock_description_editorial_uses_ai_guess_as_last_resort():
    meta = ImageMetadata(date_created="20250830")
    result = build_shutterstock_description(
        meta, DESC, location_guess="Edinburgh, UK", editorial=True
    )
    assert result == EDITORIAL_DESC


def test_build_shutterstock_description_falls_back_when_location_unresolvable():
    meta = ImageMetadata(date_created="20250830")
    result = build_shutterstock_description(meta, DESC, editorial=True)
    assert result == DESC


def test_build_shutterstock_description_falls_back_when_date_missing():
    meta = ImageMetadata(iptc_city="Edinburgh", iptc_country="UK")
    result = build_shutterstock_description(meta, DESC, editorial=True)
    assert result == DESC


def test_resolve_editorial_location_prefers_deterministic_over_ai_guess():
    meta = ImageMetadata(iptc_city="Edinburgh", iptc_country="UK")
    result = resolve_editorial_location(meta, location_guess="Paris, France")
    assert result == "Edinburgh, UK"


def test_resolve_editorial_location_falls_back_to_ai_guess():
    result = resolve_editorial_location(ImageMetadata(), location_guess="Paris, France")
    assert result == "Paris, France"


def test_resolve_editorial_dateline_resolved():
    meta = ImageMetadata(
        iptc_city="Edinburgh", iptc_country="UK", date_created="20250830"
    )
    assert resolve_editorial_dateline(meta) == ("Edinburgh, UK", "August 30, 2025")


def test_resolve_editorial_dateline_none_when_location_missing():
    meta = ImageMetadata(date_created="20250830")
    assert resolve_editorial_dateline(meta) is None


def test_resolve_editorial_dateline_none_when_date_missing():
    meta = ImageMetadata(iptc_city="Edinburgh", iptc_country="UK")
    assert resolve_editorial_dateline(meta) is None
