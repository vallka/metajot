from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from metajot.ai import AIResponse, generate_metadata
from metajot.metadata import ImageMetadata, read_metadata


class ProcessingWorker(QThread):
    """Runs AI metadata generation for a batch of images off the UI thread.
    stop() takes effect between photos - an in-flight AI request for the
    current photo is allowed to finish."""

    # Signals carry the caller's index for each job (e.g. its position in the
    # full photo list), not the position within this batch.
    image_started = Signal(int)
    image_done = Signal(int, object, object)  # index, ImageMetadata, AIResponse
    image_failed = Signal(int, str)
    finished_all = Signal()

    def __init__(self, jobs: list[tuple[int, Path, Optional[ImageMetadata]]]):
        """Each job is (index, path, context): context is the metadata to
        give the AI instead of what's in the file - e.g. unsaved edits made
        in the GUI - or None to read it from the file."""
        super().__init__()
        self.jobs = jobs
        self.stop_requested = False

    def stop(self) -> None:
        self.stop_requested = True

    def run(self) -> None:
        for index, path, context in self.jobs:
            if self.stop_requested:
                break
            self.image_started.emit(index)
            try:
                current_meta: ImageMetadata = context or read_metadata(path)
                ai_data: AIResponse = generate_metadata(path, current_meta)
                self.image_done.emit(index, current_meta, ai_data)
            except Exception as e:
                self.image_failed.emit(index, str(e))
        self.finished_all.emit()
