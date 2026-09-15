import shutil
from pathlib import Path

import pytest

from metajot.xmp import _find_xmp_segment, read_xmp_packet, write_xmp_metadata

FIXTURE = Path(__file__).parent / "fixtures" / "25-06-12-DSC00334-1.jpg"


@pytest.fixture
def image_copy(tmp_path):
    dst = tmp_path / "photo.jpg"
    shutil.copy(FIXTURE, dst)
    return dst


def test_write_xmp_metadata_sets_dc_properties(image_copy):
    ok = write_xmp_metadata(
        image_copy,
        title="A Test Title",
        description="A test description.",
        keywords=["one", "two", "three"],
    )
    assert ok is True

    xml = read_xmp_packet(image_copy.read_bytes())
    assert "<dc:title>" in xml
    assert "A Test Title" in xml
    assert "A test description." in xml
    assert "<dc:subject>" in xml
    for keyword in ("one", "two", "three"):
        assert f"<rdf:li>{keyword}</rdf:li>" in xml


def test_write_xmp_metadata_preserves_other_properties(image_copy):
    original_xml = read_xmp_packet(image_copy.read_bytes())
    assert original_xml is not None  # fixture already carries Capture One XMP

    write_xmp_metadata(
        image_copy, title="New Title", description="New description.", keywords=["kw"]
    )

    new_xml = read_xmp_packet(image_copy.read_bytes())
    # Non dc:title/description/subject properties (creator tool, camera info,
    # rights, etc.) must survive untouched.
    for tag in ("xmp:CreatorTool", "tiff:Make", "dc:creator", "dc:rights"):
        if tag in original_xml:
            assert tag in new_xml


def test_write_xmp_metadata_replaces_existing_segment_in_place(image_copy):
    data_before = image_copy.read_bytes()
    seg_before = _find_xmp_segment(data_before)
    assert seg_before is not None

    write_xmp_metadata(image_copy, title="T", description="D", keywords=[])

    data_after = image_copy.read_bytes()
    # Still exactly one XMP segment, and the file stays a valid JPEG.
    assert data_after[0:2] == b"\xff\xd8"
    assert data_after.count(b"http://ns.adobe.com/xap/1.0/\x00") == 1


def test_write_xmp_metadata_inserts_segment_when_absent(image_copy):
    data = image_copy.read_bytes()
    start, end = _find_xmp_segment(data)
    stripped = data[:start] + data[end:]
    image_copy.write_bytes(stripped)
    assert read_xmp_packet(image_copy.read_bytes()) is None

    ok = write_xmp_metadata(
        image_copy, title="Inserted Title", description="Inserted desc.", keywords=["x"]
    )
    assert ok is True

    xml = read_xmp_packet(image_copy.read_bytes())
    assert xml is not None
    assert "Inserted Title" in xml
