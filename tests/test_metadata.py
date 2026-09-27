import logging
import shutil
from pathlib import Path

import pytest
from exif import Image as ExifImage
from iptcinfo3 import IPTCInfo

from metajot.location import Location
from metajot.metadata import (
    ImageMetadata,
    _exif_datetime_to_iptc_date,
    read_metadata,
    resolve_deterministic_location,
    write_editorial_flag,
    write_metadata,
)
from metajot.xmp import read_xmp_packet, write_xmp_metadata

logging.getLogger("iptcinfo").setLevel(logging.ERROR)

FIXTURE = Path(__file__).parent / "fixtures" / "25-06-12-DSC00334-1.jpg"


@pytest.fixture
def image_copy(tmp_path):
    dst = tmp_path / "photo.jpg"
    shutil.copy(FIXTURE, dst)
    return dst


def test_write_metadata_syncs_iptc_exif_and_xmp(image_copy):
    ok = write_metadata(
        image_copy,
        title="Synced Title",
        description="Synced description.",
        keywords=["kw1", "kw2"],
    )
    assert ok is True

    read_back = read_metadata(image_copy)
    assert read_back.title == "Synced Title"
    assert read_back.description == "Synced description."
    assert read_back.keywords == ["kw1", "kw2"]

    with open(image_copy, "rb") as f:
        exif_img = ExifImage(f)
    assert exif_img.image_description == "Synced description."

    xml = read_xmp_packet(image_copy.read_bytes())
    assert "Synced Title" in xml
    assert "Synced description." in xml
    assert "<rdf:li>kw1</rdf:li>" in xml
    assert "<rdf:li>kw2</rdf:li>" in xml


def test_write_metadata_survives_non_ascii_description(image_copy):
    # EXIF's ImageDescription tag is ASCII-only per spec; the `exif` library
    # used to raise on a plain em dash, which aborted write_metadata()
    # entirely even though the IPTC save just before it had already
    # succeeded - leaving IPTC/XMP out of sync and the file reported as
    # failed. write_metadata() should fall back to an ASCII-safe EXIF
    # description instead of failing the whole write.
    ok = write_metadata(
        image_copy,
        title="Title",
        description="Café scene — street photography",
        keywords=["kw1"],
    )
    assert ok is True

    read_back = read_metadata(image_copy)
    assert read_back.description == "Café scene — street photography"
    assert read_back.keywords == ["kw1"]

    with open(image_copy, "rb") as f:
        exif_img = ExifImage(f)
    assert exif_img.image_description == "Cafe scene - street photography"


def test_processed_at_marker_distinguishes_untouched_from_written_files(image_copy):
    before = read_metadata(image_copy)
    assert before.processed_at is None

    write_metadata(image_copy, title="T", description="D", keywords=["k"])

    after = read_metadata(image_copy)
    assert after.processed_at is not None


def test_resolve_deterministic_location_prefers_iptc_over_gps():
    meta = ImageMetadata(
        iptc_city="Edinburgh",
        iptc_province_state="Scotland",
        gps_latitude=40.7128,  # NYC - should be ignored since IPTC city is set
        gps_longitude=-74.0060,
    )
    assert resolve_deterministic_location(meta) == Location(
        city="Edinburgh", province_state="Scotland"
    )


def test_resolve_deterministic_location_falls_back_to_gps():
    meta = ImageMetadata(gps_latitude=55.9533, gps_longitude=-3.1883)
    assert resolve_deterministic_location(meta) == Location(
        city="Edinburgh", country="UK"
    )


def test_resolve_deterministic_location_none_when_nothing_available():
    assert resolve_deterministic_location(ImageMetadata()) is None


def test_exif_datetime_to_iptc_date():
    assert _exif_datetime_to_iptc_date("2026:09:14 19:55:43") == "20260914"


def test_exif_datetime_to_iptc_date_invalid_returns_none():
    assert _exif_datetime_to_iptc_date("not a date") is None


def test_read_metadata_falls_back_to_exif_date_when_no_iptc_date(image_copy):
    # Camera-original JPEGs (e.g. straight off a phone) often have EXIF
    # DateTimeOriginal but no IPTC "date created", which Capture One/
    # Lightroom-style export tools set instead.
    iptc = IPTCInfo(image_copy, force=True)
    iptc["date created"] = None
    iptc.save(options=["overwrite"])

    with open(image_copy, "rb") as f:
        exif_img = ExifImage(f)
    exif_img.datetime_original = "2026:09:14 19:55:43"
    with open(image_copy, "wb") as f:
        f.write(exif_img.get_file())

    meta = read_metadata(image_copy)
    assert meta.date_created == "20260914"


def _clear_iptc_location(path):
    iptc = IPTCInfo(path, force=True)
    for key in ("city", "province/state", "country/primary location name"):
        iptc[key] = None
    iptc.save(options=["overwrite"])


def test_write_metadata_saves_location_to_iptc_and_xmp(image_copy):
    _clear_iptc_location(image_copy)
    location = Location(
        city="Paris", province_state="Ile-de-France", country="France"
    )

    ok = write_metadata(image_copy, "T", "D", ["k"], location=location)
    assert ok is True

    assert read_metadata(image_copy).embedded_location() == location

    xml = read_xmp_packet(image_copy.read_bytes())
    assert 'photoshop:City="Paris"' in xml
    assert 'photoshop:State="Ile-de-France"' in xml
    assert 'photoshop:Country="France"' in xml


def test_write_metadata_clears_empty_location_parts(image_copy):
    texas = Location(city="Austin", province_state="TX", country="USA")
    paris = Location(city="Paris", country="France")
    write_metadata(image_copy, "T", "D", ["k"], location=texas)
    write_metadata(image_copy, "T", "D", ["k"], location=paris)
    assert read_metadata(image_copy).embedded_location() == paris


def test_write_metadata_without_location_keeps_existing(image_copy):
    location = Location(city="Paris", country="France")
    write_metadata(image_copy, "T", "D", ["k"], location=location)
    write_metadata(image_copy, "T2", "D2", ["k2"])
    assert read_metadata(image_copy).embedded_location() == location


def test_read_metadata_falls_back_to_xmp_location(image_copy):
    # Some tools write the location to XMP only, leaving IPTC empty.
    _clear_iptc_location(image_copy)
    rome = Location(city="Rome", country="Italy")
    write_xmp_metadata(image_copy, "T", "D", ["k"], location=rome)
    assert read_metadata(image_copy).embedded_location() == rome


def test_editorial_flag_round_trips_through_write_metadata(image_copy):
    assert read_metadata(image_copy).editorial is False
    write_metadata(image_copy, "T", "D", ["k"], editorial=True)
    assert read_metadata(image_copy).editorial is True
    write_metadata(image_copy, "T", "D", ["k"], editorial=False)
    assert read_metadata(image_copy).editorial is False


def test_write_metadata_without_editorial_keeps_existing_flag(image_copy):
    write_metadata(image_copy, "T", "D", ["k"], editorial=True)
    write_metadata(image_copy, "T2", "D2", ["k2"])
    assert read_metadata(image_copy).editorial is True


def test_write_editorial_flag_only_touches_the_flag(image_copy):
    before = read_metadata(image_copy)
    assert write_editorial_flag(image_copy, True) is True
    after = read_metadata(image_copy)
    assert after.editorial is True
    # Not stamped as processed, and nothing else changed.
    assert after.processed_at is None
    assert after.title == before.title
    assert after.keywords == before.keywords
