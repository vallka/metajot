# PyInstaller spec for the standalone MetaJot app.
#
#   uv run --group build pyinstaller packaging/metajot.spec --noconfirm
#
# Builds dist/MetaJot/ (Windows: MetaJot.exe plus its _internal folder) or
# dist/MetaJot.app (macOS). PyInstaller can't cross-compile: each platform's
# build has to run on that platform (see .github/workflows/build.yml).

import re
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
DATA_DIR = ROOT / "src" / "metajot" / "data"

version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]
# macOS wants a plain numeric version, e.g. 0.1.0a1 -> 0.1.0.
numeric_version = re.match(r"\d+(\.\d+)*", version).group(0)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(DATA_DIR), "metajot/data"),
        # metajot.__version__ is read from the installed package metadata.
        *copy_metadata("metajot"),
    ],
    # keyring finds its credential-store backends at runtime.
    hiddenimports=collect_submodules("keyring.backends"),
    excludes=["tkinter"],
)

# Qt parts a widgets-only app doesn't use, pulled in by PySide6's hooks
# (~40 MB): the software OpenGL fallback, Qt Quick/QML, PDF (via the
# imageformats/qpdf plugin), the virtual keyboard (needs Quick) and Qt's
# own UI translations.
UNUSED_QT = re.compile(
    r"opengl32sw|Qt6?(Quick|Qml|Pdf|VirtualKeyboard)|QtQuick|QtQml"
    r"|qpdf|qtvirtualkeyboard|[\\/]translations[\\/]",
    re.IGNORECASE,
)
a.binaries = [b for b in a.binaries if not UNUSED_QT.search(b[0])]
a.datas = [d for d in a.datas if not UNUSED_QT.search(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MetaJot",
    console=False,
    icon=str(DATA_DIR / "icon.ico"),
    # UPX-compressed Qt DLLs are a common cause of crashes and antivirus
    # false positives.
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MetaJot", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MetaJot.app",
        # Converted to .icns by PyInstaller (needs Pillow, already a dependency).
        icon=str(DATA_DIR / "icon.ico"),
        bundle_identifier="io.github.vallka.metajot",
        version=numeric_version,
        info_plist={
            "CFBundleDisplayName": "MetaJot",
            "NSHighResolutionCapable": True,
        },
    )
