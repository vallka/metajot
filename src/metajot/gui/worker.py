from pathlib import Path

from PySide6.QtCore import QThread, Signal

from metajot.ai import AIResponse, generate_metadata
from metajot.metadata import ImageMetadata, read_metadata


class ProcessingWorker(QThread):
    """Runs AI metadata generation for a batch of images off the UI thread.
    stop() takes effect between photos - an in-flight AI request for the
    current photo is allowed to finish."""

    image_started = Signal(int)
    image_done = Signal(int, object, object)  # row, ImageMetadata, AIResponse
    image_failed = Signal(int, str)
    finished_all = Signal()

    def __init__(self, image_paths: list[Path]):
        super().__init__()
        self.image_paths = image_paths
        self.stop_requested = False

    def stop(self) -> None:
        self.stop_requested = True

    def run(self) -> None:
        for row, path in enumerate(self.image_paths):
            if self.stop_requested:
                break
            self.image_started.emit(row)
            try:
                current_meta: ImageMetadata = read_metadata(path)
                ai_data: AIResponse = generate_metadata(path, current_meta)
                self.image_done.emit(row, current_meta, ai_data)
            except Exception as e:
                self.image_failed.emit(row, str(e))
        self.finished_all.emit()
