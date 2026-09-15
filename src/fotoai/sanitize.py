"""Text cleanup for AI-generated metadata before it's embedded or exported.

Vision models routinely produce "smart" typographic punctuation (em dashes,
curly quotes, ellipses) that plain ASCII-oriented metadata fields choke on:
EXIF's ImageDescription tag is ASCII-only per spec (the `exif` library raises
if it sees anything else, which previously aborted the whole write_metadata()
call - including the IPTC save that had already happened), and iptcinfo3
writes IPTC fields as raw UTF-8 bytes without declaring a charset, so
non-ASCII characters risk being misread as Latin-1 (mojibake) by tools that
assume IPTC's traditional default encoding.
"""

import re
import unicodedata

_TYPOGRAPHIC_REPLACEMENTS = {
    "—": "-",  # em dash —
    "–": "-",  # en dash –
    "‘": "'",  # left single quotation mark '
    "’": "'",  # right single quotation mark '
    "“": '"',  # left double quotation mark "
    "”": '"',  # right double quotation mark "
    "…": "...",  # horizontal ellipsis …
    " ": " ",  # non-breaking space
    "•": "-",  # bullet •
}


def sanitize_typography(text: str) -> str:
    """Replaces common typographic Unicode punctuation with plain ASCII
    equivalents (em dash -> "-", curly quotes -> straight quotes, etc.)."""
    for char, replacement in _TYPOGRAPHIC_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text


def to_ascii(text: str) -> str:
    """Best-effort transliteration to plain ASCII (e.g. "Café" -> "Cafe"),
    dropping any character that has no ASCII equivalent. Used as a last-resort
    fallback for EXIF's ASCII-only ImageDescription field when the text isn't
    already fully ASCII (e.g. accented place names, or typographic
    punctuation NFKD normalization doesn't decompose, like em dashes)."""
    normalized = unicodedata.normalize("NFKD", sanitize_typography(text))
    return normalized.encode("ascii", "ignore").decode("ascii")


# Shutterstock rejects CSV submissions whose Description column contains any
# of these characters.
_SHUTTERSTOCK_BANNED_CHARS = {
    "<": "",
    ">": "",
    "&": "and",
    "/": " ",
}


def sanitize_shutterstock_description(text: str) -> str:
    """Strips/replaces the characters Shutterstock bans from its Description
    column (<, >, &, /) and collapses any resulting doubled-up whitespace."""
    for char, replacement in _SHUTTERSTOCK_BANNED_CHARS.items():
        text = text.replace(char, replacement)
    return re.sub(r" {2,}", " ", text).strip()
