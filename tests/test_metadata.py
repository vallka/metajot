import logging
import shutil
from pathlib import Path

import pytest
from exif import Image as ExifImage
from iptcinfo3 import IPTCInfo

from fotoai.metadata import (
    ImageMetadata,
    _exif_datetime_to_iptc_date,
    read_metadata,
    resolve_deterministic_location,
    write_metadata,
)
from fotoai.xmp import read_xmp_packet

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
    assert resolve_deterministic_location(meta) == "Edinburgh, Scotland"


def test_resolve_deterministic_location_falls_back_to_gps():
    meta = ImageMetadata(gps_latitude=55.9533, gps_longitude=-3.1883)
    assert resolve_deterministic_location(meta) == "Edinburgh, UK"


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
