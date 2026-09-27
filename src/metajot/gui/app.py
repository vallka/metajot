import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from metajot import __version__
from metajot.gui.main_window import MainWindow

ICON_PATH = Path(__file__).resolve().parent.parent / "data" / "icon.ico"


def _set_windows_app_id() -> None:
    """Gives the process its own taskbar identity. Otherwise Windows groups
    the window under python.exe and shows Python's icon in the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MetaJot.MetaJot"
        )
    except Exception:
        pass  # cosmetic only


def main() -> None:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("MetaJot")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
