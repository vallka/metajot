import re
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("metajot")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"


def display_version() -> str:
    """The version for people, e.g. "0.1.0a1" -> "0.1.0 alpha 1"."""
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(a|b|rc)(\d+)", __version__)
    if not match:
        return __version__
    release, stage, number = match.groups()
    stage_name = {"a": "alpha", "b": "beta", "rc": "RC"}[stage]
    return f"{release} {stage_name} {number}"
