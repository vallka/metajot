import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from exif import Image as ExifImage
from iptcinfo3 import IPTCInfo

# iptcinfo3 can be very noisy in the console, so we suppress its warnings
logging.getLogger("iptcinfo").setLevel(logging.ERROR)


@dataclass
class ImageMetadata:
    title: Optional[str] = None
    description: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    # Raw GPS coordinates if found (just strings representing the tuple or degrees for context)
    location_data: Optional[str] = None


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

    except Exception as e:
        print(f"Warning: Failed to read IPTC from {image_path}: {e}")

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


def write_metadata(image_path: Path, title: str, description: str, keywords: List[str]) -> bool:
    """Writes new IPTC Title, Description, and Keywords to the image."""
    try:
        iptc = IPTCInfo(image_path, force=True)
        
        # In IPTC:
        # 'object name' often mapped to Title in software (like Capture One / Lightroom)
        # 'caption/abstract' is Description
        iptc["object name"] = title.encode("utf-8")
        iptc["caption/abstract"] = description.encode("utf-8")
        
        # Clear existing keywords and write new ones
        iptc["keywords"] = [k.encode("utf-8") for k in keywords]

        # iptc.save() writes the new data back to image_path directly,
        # backing up the previous version to "image_path~".
        return bool(iptc.save())
    except Exception as e:
        print(f"Error writing metadata to {image_path}: {e}")
        return False
