import shutil
from pathlib import Path

import pytest
from exif import Image as ExifImage

from fotoai.metadata import read_metadata, write_metadata
from fotoai.xmp import read_xmp_packet

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
