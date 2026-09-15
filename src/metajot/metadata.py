import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from exif import Image as ExifImage
from iptcinfo3 import IPTCInfo

from metajot.location import format_editorial_location, reverse_geocode
from metajot.sanitize import to_ascii
from metajot.xmp import read_metajot_processed_at, read_xmp_packet, write_xmp_metadata

# iptcinfo3 can be very noisy in the console, so we suppress its warnings
logging.getLogger("iptcinfo").setLevel(logging.ERROR)


@dataclass
class ImageMetadata:
    title: Optional[str] = None
    description: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    # Raw GPS coordinates if found (just strings representing the tuple or degrees for context)
    location_data: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    # Existing IPTC location fields, if the original editing tool (e.g.
    # Capture One) already filled them in.
    iptc_city: Optional[str] = None
    iptc_province_state: Optional[str] = None
    iptc_country: Optional[str] = None
    # IPTC "date created" (CCYYMMDD), needed for editorial datelines.
    date_created: Optional[str] = None
    # Adobe Stock has no standard metadata field for its category, so we
    # repurpose the legacy IPTC "category"/"supplemental category" datasets
    # (2:15 and 2:20) - unused elsewhere in this app - to keep it embedded
    # alongside the rest of the metadata instead of only living in a CSV.
    adobe_category_id: Optional[str] = None
    shutterstock_categories: List[str] = field(default_factory=list)
    # Set only when a previous MetaJot run stamped the XMP metajot:ProcessedAt
    # marker into this file - the authoritative "already processed" signal,
    # independent of whether category data happens to be filled in.
    processed_at: Optional[str] = None


def _dms_to_decimal(dms: tuple, ref: Optional[str]) -> Optional[float]:
    """Converts an EXIF (degrees, minutes, seconds) GPS tuple to decimal
    degrees, negative for South/West as the ref hemisphere requires."""
    try:
        degrees, minutes, seconds = dms
        decimal = degrees + minutes / 60 + seconds / 3600
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _exif_datetime_to_iptc_date(exif_datetime: str) -> Optional[str]:
    """Converts an EXIF DateTimeOriginal/DateTime value ("YYYY:MM:DD
    HH:MM:SS") to the IPTC "date created" format (CCYYMMDD)."""
    date_part = exif_datetime.split(" ", 1)[0]
    digits = date_part.replace(":", "")
    return digits if len(digits) == 8 and digits.isdigit() else None


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

        if city_bytes := iptc["city"]:
            meta.iptc_city = decode_iptc_value(city_bytes)
        if province_bytes := iptc["province/state"]:
            meta.iptc_province_state = decode_iptc_value(province_bytes)
        if country_bytes := iptc["country/primary location name"]:
            meta.iptc_country = decode_iptc_value(country_bytes)
        if date_bytes := iptc["date created"]:
            meta.date_created = decode_iptc_value(date_bytes)

    except Exception as e:
        print(f"Warning: Failed to read IPTC from {image_path}: {e}")

    # Read the metajot:ProcessedAt marker from XMP, if any
    try:
        xmp_xml = read_xmp_packet(image_path.read_bytes())
        if xmp_xml:
            meta.processed_at = read_metajot_processed_at(xmp_xml)
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
                    meta.gps_latitude = _dms_to_decimal(lat, lat_ref)
                    meta.gps_longitude = _dms_to_decimal(lon, lon_ref)

                # Camera-original JPEGs (e.g. straight off a phone) often
                # carry EXIF DateTimeOriginal but no IPTC "date created" -
                # that field tends to only get set by editing tools like
                # Capture One/Lightroom on export. Fall back to it so the
                # editorial dateline still has a date to work with.
                if not meta.date_created:
                    exif_datetime = exif_img.get("datetime_original") or exif_img.get(
                        "datetime"
                    )
                    if exif_datetime:
                        meta.date_created = _exif_datetime_to_iptc_date(exif_datetime)
    except Exception as e:
        print(f"Warning: Failed to read EXIF from {image_path}: {e}")

    return meta


def resolve_deterministic_location(meta: ImageMetadata) -> Optional[str]:
    """Resolves an editorial-style "City, State/Country" location for a photo
    without needing AI: prefers IPTC location fields already filled in by the
    original editing tool, then falls back to reverse-geocoding embedded GPS
    coordinates. Returns None if neither is available - callers should then
    fall back to asking the AI to infer a location from keywords/visuals."""
    if meta.iptc_city:
        region = meta.iptc_province_state or meta.iptc_country
        if region:
            return f"{meta.iptc_city}, {region}"
        return meta.iptc_city

    if meta.gps_latitude is not None and meta.gps_longitude is not None:
        city = reverse_geocode(meta.gps_latitude, meta.gps_longitude)
        if city:
            return format_editorial_location(city)

    return None


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
        try:
            exif_img.image_description = description
        except Exception:
            # EXIF's ImageDescription tag is ASCII-only per spec; the `exif`
            # library raises on anything else. IPTC/XMP already carry the
            # full-fidelity UTF-8 description, so fall back to a
            # transliterated ASCII copy here rather than losing the rest of
            # the write over an EXIF-only mirror field.
            exif_img.image_description = to_ascii(description)
        with open(image_path, "wb") as f:
            f.write(exif_img.get_file())

        return write_xmp_metadata(image_path, title, description, keywords)
    except Exception as e:
        print(f"Error writing metadata to {image_path}: {e}")
        return False
