import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from exif import Image as ExifImage
from iptcinfo3 import IPTCInfo

from fotoai.xmp import read_fotoai_processed_at, read_xmp_packet, write_xmp_metadata

# iptcinfo3 can be very noisy in the console, so we suppress its warnings
logging.getLogger("iptcinfo").setLevel(logging.ERROR)


@dataclass
class ImageMetadata:
    title: Optional[str] = None
    description: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    # Raw GPS coordinates if found (just strings representing the tuple or degrees for context)
    location_data: Optional[str] = None
    # Adobe Stock has no standard metadata field for its category, so we
    # repurpose the legacy IPTC "category"/"supplemental category" datasets
    # (2:15 and 2:20) - unused elsewhere in this app - to keep it embedded
    # alongside the rest of the metadata instead of only living in a CSV.
    adobe_category_id: Optional[str] = None
    shutterstock_categories: List[str] = field(default_factory=list)
    # Set only when a previous FotoAI run stamped the XMP fotoai:ProcessedAt
    # marker into this file - the authoritative "already processed" signal,
    # independent of whether category data happens to be filled in.
    processed_at: Optional[str] = None


def decode_iptc_value(value) -> Optional[str]:
    """Helper to decode IPTC byte values to string."""
    if not value:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return str(value)
    return str(value)


def read_metadata(image_path: Path) -> ImageMetadata:
    """Reads existing IPTC and EXIF data from an image."""
    meta = ImageMetadata()

    # Read IPTC Data (Keywords, Title, Description)
    try:
        iptc = IPTCInfo(image_path, force=True)

        if title_bytes := iptc["object name"]:
            meta.title = decode_iptc_value(title_bytes)
            
        if desc_bytes := iptc["caption/abstract"]:
            meta.description = decode_iptc_value(desc_bytes)

        if iptc["keywords"]:
            meta.keywords = [decode_iptc_value(k) for k in iptc["keywords"] if k]

        if category_bytes := iptc["category"]:
            meta.adobe_category_id = decode_iptc_value(category_bytes)

        supplemental = iptc["supplemental category"] or []
        meta.shutterstock_categories = [
            decoded for c in supplemental if c and (decoded := decode_iptc_value(c))
        ]

    except Exception as e:
        print(f"Warning: Failed to read IPTC from {image_path}: {e}")

    # Read the fotoai:ProcessedAt marker from XMP, if any
    try:
        xmp_xml = read_xmp_packet(image_path.read_bytes())
        if xmp_xml:
            meta.processed_at = read_fotoai_processed_at(xmp_xml)
    except Exception as e:
        print(f"Warning: Failed to read XMP from {image_path}: {e}")

    # Read EXIF Data
    try:
        with open(image_path, "rb") as f:
            exif_img = ExifImage(f)
            if exif_img.has_exif:
                lat = exif_img.get("gps_latitude")
                lat_ref = exif_img.get("gps_latitude_ref")
                lon = exif_img.get("gps_longitude")
                lon_ref = exif_img.get("gps_longitude_ref")
                
                if lat and lon:
                    meta.location_data = f"Lat: {lat} {lat_ref}, Lon: {lon} {lon_ref}"
    except Exception as e:
        print(f"Warning: Failed to read EXIF from {image_path}: {e}")

    return meta


def write_metadata(
    image_path: Path,
    title: str,
    description: str,
    keywords: List[str],
    adobe_category_id: Optional[str] = None,
    shutterstock_categories: Optional[List[str]] = None,
) -> bool:
    """Writes new IPTC Title, Description, Keywords, and categories to the image."""
    try:
        iptc = IPTCInfo(image_path, force=True)

        # In IPTC:
        # 'object name' often mapped to Title in software (like Capture One / Lightroom)
        # 'caption/abstract' is Description
        iptc["object name"] = title.encode("utf-8")
        iptc["headline"] = title.encode("utf-8")
        iptc["caption/abstract"] = description.encode("utf-8")

        # Clear existing keywords and write new ones
        iptc["keywords"] = [k.encode("utf-8") for k in keywords]

        # Adobe Stock's category and Shutterstock's categories have no
        # dedicated metadata field, so they're stored in the legacy IPTC
        # "category"/"supplemental category" datasets (unused elsewhere)
        # to keep them embedded with the rest of the metadata.
        if adobe_category_id:
            iptc["category"] = adobe_category_id.encode("utf-8")
        if shutterstock_categories:
            iptc["supplemental category"] = [
                c.encode("utf-8") for c in shutterstock_categories
            ]

        # "overwrite" makes iptc.save() write back to image_path directly
        # without leaving an "image_path~" backup of the previous version.
        if not iptc.save(options=["overwrite"]):
            return False

        # IPTC IIM alone isn't enough: Windows Explorer's Title/Subject
        # columns and some stock sites (e.g. Pexels, Dreamstime) read XMP
        # dc:title/dc:description/dc:subject instead, and ignore IPTC
        # entirely. Mirror the same values into EXIF and XMP so every reader
        # sees consistent metadata regardless of which block it trusts.
        with open(image_path, "rb") as f:
            exif_img = ExifImage(f)
        exif_img.image_description = description
        with open(image_path, "wb") as f:
            f.write(exif_img.get_file())

        return write_xmp_metadata(image_path, title, description, keywords)
    except Exception as e:
        print(f"Error writing metadata to {image_path}: {e}")
        return False
