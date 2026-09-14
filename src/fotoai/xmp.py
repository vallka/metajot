"""Pure-Python reader/writer for the XMP packet embedded in a JPEG's APP1 segment.

`metadata.write_metadata()` writes title/description/keywords into legacy IPTC
IIM fields, but several important readers ignore IPTC and read the XMP
`dc:title` / `dc:description` / `dc:subject` properties instead - notably
Windows Explorer's Title/Subject columns, and some stock sites' keyword
ingestion (they fall back to whatever XMP keywords were already embedded by
the original editing tool, e.g. Capture One). This module keeps those three
XMP properties in sync with what's written to IPTC, patching them in place and
leaving every other XMP property (camera/lens info, hierarchical keywords,
creator, rights, etc.) exactly as it was.
"""

import struct
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

XMP_SIGNATURE = b"http://ns.adobe.com/xap/1.0/\x00"

NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_XML = "http://www.w3.org/XML/1998/namespace"

# Nominal namespace identifying FotoAI's own custom property - doesn't need to
# resolve to anything, it just has to be globally unique, per XMP convention.
NS_FOTOAI = "https://github.com/vallka/fotoai/ns/1.0/"
PROCESSED_AT_TAG = "ProcessedAt"

ET.register_namespace("x", NS_X)
ET.register_namespace("rdf", NS_RDF)
ET.register_namespace("dc", NS_DC)
ET.register_namespace("fotoai", NS_FOTOAI)

# Other namespaces commonly found in XMP packets written by camera/editing
# tools (Capture One, Lightroom, Photoshop). Registering them isn't required
# for correctness - RDF is namespace-URI-based, not prefix-based - but it
# keeps properties we don't touch serialized under their conventional prefix
# instead of an auto-generated ns0/ns1/... one, which is much easier to read
# and diff.
ET.register_namespace("xmp", "http://ns.adobe.com/xap/1.0/")
ET.register_namespace("tiff", "http://ns.adobe.com/tiff/1.0/")
ET.register_namespace("exif", "http://ns.adobe.com/exif/1.0/")
ET.register_namespace("exifEX", "http://cipa.jp/exif/1.0/")
ET.register_namespace("aux", "http://ns.adobe.com/exif/1.0/aux/")
ET.register_namespace("photoshop", "http://ns.adobe.com/photoshop/1.0/")
ET.register_namespace("lr", "http://ns.adobe.com/lightroom/1.0/")
ET.register_namespace("Iptc4xmpCore", "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/")
ET.register_namespace("mwg-rs", "http://www.metadataworkinggroup.com/schemas/regions/")
ET.register_namespace("crs", "http://ns.adobe.com/camera-raw-settings/1.0/")


def _qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _iter_jpeg_segments(data: bytes):
    """Yields (marker, seg_start, seg_end) for each marker segment up to the
    start-of-scan; seg_end is exclusive and includes the marker + length bytes."""
    if data[0:2] != b"\xff\xd8":
        raise ValueError("Not a JPEG file (missing SOI marker)")
    pos = 2
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xDA:  # Start of Scan: image data follows, nothing more to read
            break
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        start = pos
        end = pos + 2 + length
        yield marker, start, end
        pos = end


def _find_xmp_segment(data: bytes):
    sig_len = len(XMP_SIGNATURE)
    for marker, start, end in _iter_jpeg_segments(data):
        if marker == 0xE1 and data[start + 4 : start + 4 + sig_len] == XMP_SIGNATURE:
            return start, end
    return None


def _leading_app_segments_end(data: bytes) -> int:
    """Position right after the run of APPn segments (0xE0-0xEF) at the top of
    the file - the conventional, always-valid place to insert a new APP1 XMP
    segment when the file doesn't already have one."""
    pos = 2
    for marker, start, end in _iter_jpeg_segments(data):
        if 0xE0 <= marker <= 0xEF:
            pos = end
        else:
            break
    return pos


def read_xmp_packet(data: bytes) -> Optional[str]:
    """Returns the raw XMP XML packet text embedded in a JPEG, if any."""
    seg = _find_xmp_segment(data)
    if not seg:
        return None
    start, end = seg
    payload = data[start + 4 : end]
    return payload[len(XMP_SIGNATURE) :].decode("utf-8", errors="replace")


def _new_xmp_root() -> ET.Element:
    xmpmeta = ET.Element(_qn(NS_X, "xmpmeta"))
    rdf = ET.SubElement(xmpmeta, _qn(NS_RDF, "RDF"))
    ET.SubElement(rdf, _qn(NS_RDF, "Description"), {_qn(NS_RDF, "about"): ""})
    return xmpmeta


def _parse_xmp_root(xml_text: str) -> ET.Element:
    # The packet is wrapped in <?xpacket ...?> processing instructions and may
    # have trailing whitespace padding - both are valid "Misc" content around
    # the root element per the XML spec, so ElementTree parses this as-is.
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        return _new_xmp_root()


def _find_or_create_rdf(root: ET.Element) -> ET.Element:
    rdf = root.find(_qn(NS_RDF, "RDF"))
    if rdf is None:
        rdf = ET.SubElement(root, _qn(NS_RDF, "RDF"))
    return rdf


def _find_or_create_description(rdf: ET.Element) -> ET.Element:
    desc = rdf.find(_qn(NS_RDF, "Description"))
    if desc is None:
        about_attr = {_qn(NS_RDF, "about"): ""}
        desc = ET.SubElement(rdf, _qn(NS_RDF, "Description"), about_attr)
    return desc


def _set_lang_alt(desc: ET.Element, tag: str, value: str) -> None:
    """Sets a dc: language-alternative property (dc:title / dc:description) to
    a single x-default value, replacing any existing value for that property."""
    existing = desc.find(_qn(NS_DC, tag))
    if existing is not None:
        desc.remove(existing)
    el = ET.SubElement(desc, _qn(NS_DC, tag))
    alt = ET.SubElement(el, _qn(NS_RDF, "Alt"))
    li = ET.SubElement(alt, _qn(NS_RDF, "li"), {_qn(NS_XML, "lang"): "x-default"})
    li.text = value


def _set_bag(desc: ET.Element, tag: str, values: List[str]) -> None:
    """Sets a dc: bag property (dc:subject) to the given values, replacing any
    existing list for that property."""
    existing = desc.find(_qn(NS_DC, tag))
    if existing is not None:
        desc.remove(existing)
    el = ET.SubElement(desc, _qn(NS_DC, tag))
    bag = ET.SubElement(el, _qn(NS_RDF, "Bag"))
    for value in values:
        li = ET.SubElement(bag, _qn(NS_RDF, "li"))
        li.text = value


def read_fotoai_processed_at(xml_text: str) -> Optional[str]:
    """Returns the fotoai:ProcessedAt timestamp recorded by a previous FotoAI
    run, if any - the marker used to tell already-processed files apart from
    untouched ones when a folder is reopened."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    rdf = root.find(_qn(NS_RDF, "RDF"))
    if rdf is None:
        return None
    desc = rdf.find(_qn(NS_RDF, "Description"))
    if desc is None:
        return None
    return desc.get(_qn(NS_FOTOAI, PROCESSED_AT_TAG))


def build_updated_xmp(
    existing_xml: Optional[str],
    title: str,
    description: str,
    keywords: List[str],
    processed_at: Optional[str] = None,
) -> str:
    """Returns an XMP packet with dc:title/dc:description/dc:subject set to the
    given values, preserving every other property already in existing_xml.
    Also stamps fotoai:ProcessedAt (current UTC time by default) as an
    unambiguous "this file was processed by FotoAI" marker, independent of
    whatever category data happens to be filled in."""
    root = _parse_xmp_root(existing_xml) if existing_xml else _new_xmp_root()
    rdf = _find_or_create_rdf(root)
    desc = _find_or_create_description(rdf)
    _set_lang_alt(desc, "title", title)
    _set_lang_alt(desc, "description", description)
    _set_bag(desc, "subject", keywords)
    desc.set(
        _qn(NS_FOTOAI, PROCESSED_AT_TAG),
        processed_at or datetime.now(timezone.utc).isoformat(),
    )

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    packet = (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        + xml_bytes
        + b'<?xpacket end="w"?>'
    )
    return packet.decode("utf-8")


def _build_xmp_segment(xmp_xml: str) -> bytes:
    payload = XMP_SIGNATURE + xmp_xml.encode("utf-8")
    length = len(payload) + 2  # segment length includes the 2 length bytes themselves
    if length > 0xFFFF:
        raise ValueError("XMP packet is too large to fit in a single APP1 segment")
    return b"\xff\xe1" + struct.pack(">H", length) + payload


def write_xmp_metadata(
    image_path: Path, title: str, description: str, keywords: List[str]
) -> bool:
    """Writes title/description/keywords into the JPEG's XMP dc:title,
    dc:description and dc:subject properties, creating the XMP packet if the
    file doesn't have one yet. Leaves every other XMP property untouched.
    Also stamps a fotoai:ProcessedAt marker (see build_updated_xmp)."""
    try:
        data = image_path.read_bytes()
        existing_xml = read_xmp_packet(data)
        new_xml = build_updated_xmp(existing_xml, title, description, keywords)
        new_segment = _build_xmp_segment(new_xml)

        seg = _find_xmp_segment(data)
        if seg:
            start, end = seg
            new_data = data[:start] + new_segment + data[end:]
        else:
            insert_at = _leading_app_segments_end(data)
            new_data = data[:insert_at] + new_segment + data[insert_at:]

        image_path.write_bytes(new_data)
        return True
    except Exception as e:
        print(f"Error writing XMP metadata to {image_path}: {e}")
        return False
