from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fotoai.ai import (
    ADOBE_CATEGORY_IDS,
    AdobeStockCategory,
    AIResponse,
    ShutterstockCategory,
    build_shutterstock_description,
    resolve_editorial_dateline,
)
from fotoai.exporter import (
    ExportRecord,
    export_adobe_stock_csv,
    export_shutterstock_csv,
)
from fotoai.gui.worker import ProcessingWorker
from fotoai.metadata import ImageMetadata, read_metadata, write_metadata

THUMBNAIL_SIZE = 96
NO_SECONDARY = "(none)"

COL_THUMB = 0
COL_FILENAME = 1
COL_TITLE = 2
COL_DESCRIPTION = 3
COL_KEYWORDS = 4
COL_ADOBE_CATEGORY = 5
COL_SHUTTER_PRIMARY = 6
COL_SHUTTER_SECONDARY = 7
COL_EDITORIAL = 8
COL_STATUS = 9
COLUMN_COUNT = 10

COLUMN_HEADERS = [
    "",
    "Filename",
    "Title",
    "Description",
    "Keywords",
    "Adobe Category",
    "Shutterstock 1",
    "Shutterstock 2",
    "Editorial",
    "Status",
]

# Reverse of ai.ADOBE_CATEGORY_IDS, to map the numeric ID stored on disk back
# to the category name the combo box displays.
ADOBE_CATEGORY_NAMES_BY_ID = {str(v): k for k, v in ADOBE_CATEGORY_IDS.items()}


@dataclass
class RowState:
    path: Path
    current_meta: Optional[ImageMetadata] = None
    ai_data: Optional[AIResponse] = None


def load_thumbnail(path: Path, size: int = THUMBNAIL_SIZE) -> QPixmap:
    """Decodes directly at thumbnail resolution instead of full size, since
    these source JPEGs are commonly 10+ MB."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original_size = reader.size()
    if original_size.isValid():
        scaled = original_size.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio
        )
        reader.setScaledSize(scaled)
    return QPixmap.fromImage(reader.read())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FotoAI")
        self.resize(1300, 700)

        self.directory: Optional[Path] = None
        self.rows: list[RowState] = []
        self.worker: Optional[ProcessingWorker] = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        select_btn = QPushButton("Select Folder...")
        select_btn.clicked.connect(self.select_folder)
        self.folder_label = QLabel("No folder selected")
        self.process_btn = QPushButton("Process with AI")
        self.process_btn.clicked.connect(self.start_processing)
        self.process_btn.setEnabled(False)
        self.write_btn = QPushButton("Write Metadata && Export CSVs")
        self.write_btn.clicked.connect(self.write_and_export)
        self.write_btn.setEnabled(False)
        top_bar.addWidget(select_btn)
        top_bar.addWidget(self.folder_label, 1)
        top_bar.addWidget(self.process_btn)
        top_bar.addWidget(self.write_btn)
        layout.addLayout(top_bar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setDefaultSectionSize(THUMBNAIL_SIZE + 8)
        layout.addWidget(self.table)

    def select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select photo folder")
        if not folder:
            return
        self.directory = Path(folder)
        self.folder_label.setText(str(self.directory))

        images = sorted(
            p for p in self.directory.iterdir() if p.suffix.lower() in (".jpg", ".jpeg")
        )
        self._load_images(images)

    def _load_images(self, images: list[Path]) -> None:
        self.rows = [RowState(path=p) for p in images]
        self.table.setRowCount(len(images))

        for row, path in enumerate(images):
            # read_metadata() is the single "master" place FotoAI's own
            # writer keeps IPTC/EXIF/XMP in sync through, so reopening a
            # processed folder shows exactly what was last written, however
            # it was written (title/description/keywords all come from IPTC;
            # the fotoai:ProcessedAt marker comes from XMP).
            existing_meta = read_metadata(path)
            self.rows[row].current_meta = existing_meta

            thumb_label = QLabel()
            thumb_label.setPixmap(load_thumbnail(path))
            self.table.setCellWidget(row, COL_THUMB, thumb_label)
            self.table.setItem(row, COL_FILENAME, self._readonly_item(path.name))
            title_item = QTableWidgetItem(existing_meta.title or "")
            self.table.setItem(row, COL_TITLE, title_item)
            desc_item = QTableWidgetItem(existing_meta.description or "")
            self.table.setItem(row, COL_DESCRIPTION, desc_item)
            keywords_item = QTableWidgetItem(", ".join(existing_meta.keywords))
            self.table.setItem(row, COL_KEYWORDS, keywords_item)

            adobe_combo = self._make_adobe_combo()
            adobe_id = existing_meta.adobe_category_id or ""
            adobe_name = ADOBE_CATEGORY_NAMES_BY_ID.get(adobe_id)
            if adobe_name:
                adobe_combo.setCurrentText(adobe_name)
            self.table.setCellWidget(row, COL_ADOBE_CATEGORY, adobe_combo)

            primary_combo = self._make_shutter_combo()
            secondary_combo = self._make_shutter_combo(allow_none=True)
            categories = existing_meta.shutterstock_categories
            if categories:
                primary_combo.setCurrentText(categories[0])
            if len(categories) > 1:
                secondary_combo.setCurrentText(categories[1])
            self.table.setCellWidget(row, COL_SHUTTER_PRIMARY, primary_combo)
            self.table.setCellWidget(row, COL_SHUTTER_SECONDARY, secondary_combo)

            editorial_checkbox = self._make_editorial_checkbox()
            self.table.setCellWidget(row, COL_EDITORIAL, editorial_checkbox)

            status = "Done" if existing_meta.processed_at else "Pending"
            self.table.setItem(row, COL_STATUS, self._readonly_item(status))

        self.process_btn.setEnabled(bool(images))
        # write_and_export() only acts on rows with freshly-generated ai_data,
        # not merely on rows read from disk, so it stays disabled until
        # "Process with AI" actually populates that - even for rows already
        # marked Done above.
        self.write_btn.setEnabled(False)

    @staticmethod
    def _readonly_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    @staticmethod
    def _make_adobe_combo() -> QComboBox:
        combo = QComboBox()
        combo.addItems([c.value for c in AdobeStockCategory])
        return combo

    @staticmethod
    def _make_shutter_combo(allow_none: bool = False) -> QComboBox:
        combo = QComboBox()
        if allow_none:
            combo.addItem(NO_SECONDARY)
        combo.addItems([c.value for c in ShutterstockCategory])
        return combo

    @staticmethod
    def _make_editorial_checkbox() -> QCheckBox:
        checkbox = QCheckBox()
        checkbox.setToolTip(
            "Format the Shutterstock description as an editorial dateline "
            '("City, State/Country - Month Day Year: Description") for '
            "this photo."
        )
        return checkbox

    def start_processing(self) -> None:
        if not self.rows:
            return
        self.process_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self.rows))
        self.progress.setValue(0)

        self.worker = ProcessingWorker([r.path for r in self.rows])
        self.worker.image_started.connect(self._on_image_started)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.finished_all.connect(self._on_all_done)
        self.worker.start()

    def _on_image_started(self, row: int) -> None:
        self.table.item(row, COL_STATUS).setText("Processing...")

    def _on_image_done(
        self, row: int, current_meta: ImageMetadata, ai_data: AIResponse
    ) -> None:
        self.rows[row].current_meta = current_meta
        self.rows[row].ai_data = ai_data

        self.table.item(row, COL_TITLE).setText(ai_data.title)
        self.table.item(row, COL_DESCRIPTION).setText(ai_data.description)
        self.table.item(row, COL_KEYWORDS).setText(", ".join(ai_data.keywords))

        adobe_combo: QComboBox = self.table.cellWidget(row, COL_ADOBE_CATEGORY)
        adobe_combo.setCurrentText(ai_data.adobe_category.value)

        primary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_PRIMARY)
        primary_combo.setCurrentText(ai_data.shutterstock_category_primary.value)

        secondary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_SECONDARY)
        secondary_value = ai_data.shutterstock_category_secondary
        secondary_combo.setCurrentText(
            secondary_value.value if secondary_value else NO_SECONDARY
        )

        self.table.item(row, COL_STATUS).setText("Done")
        self.progress.setValue(self.progress.value() + 1)

    def _on_image_failed(self, row: int, message: str) -> None:
        self.table.item(row, COL_STATUS).setText(f"Error: {message}")
        self.progress.setValue(self.progress.value() + 1)

    def _on_all_done(self) -> None:
        self.progress.setVisible(False)
        self.process_btn.setEnabled(True)
        self.write_btn.setEnabled(any(r.ai_data for r in self.rows))

    def write_and_export(self) -> None:
        records: list[ExportRecord] = []
        failures: list[str] = []
        editorial_unresolved: list[str] = []

        for row, state in enumerate(self.rows):
            if not state.ai_data:
                continue

            title = self.table.item(row, COL_TITLE).text().strip()
            description = self.table.item(row, COL_DESCRIPTION).text().strip()
            keywords = [
                k.strip()
                for k in self.table.item(row, COL_KEYWORDS).text().split(",")
                if k.strip()
            ]

            adobe_combo: QComboBox = self.table.cellWidget(row, COL_ADOBE_CATEGORY)
            adobe_category_id = str(ADOBE_CATEGORY_IDS[adobe_combo.currentText()])

            primary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_PRIMARY)
            secondary_combo: QComboBox = self.table.cellWidget(
                row, COL_SHUTTER_SECONDARY
            )
            shutterstock_categories = [primary_combo.currentText()]
            if secondary_combo.currentText() != NO_SECONDARY:
                shutterstock_categories.append(secondary_combo.currentText())

            success = write_metadata(
                state.path,
                title,
                description,
                keywords,
                adobe_category_id,
                shutterstock_categories,
            )
            if success:
                self.table.item(row, COL_STATUS).setText("Written")

                editorial_checkbox: QCheckBox = self.table.cellWidget(
                    row, COL_EDITORIAL
                )
                editorial_requested = editorial_checkbox.isChecked()
                current_meta = state.current_meta or ImageMetadata()
                location_guess = state.ai_data.location_guess if state.ai_data else None
                shutterstock_description = build_shutterstock_description(
                    current_meta, description, location_guess, editorial_requested
                )
                # Only mark the CSV row Editorial if a dateline was actually
                # resolved and applied above - marking it Yes without one
                # would get the submission rejected by Shutterstock.
                dateline_applied = editorial_requested and resolve_editorial_dateline(
                    current_meta, location_guess
                )
                if editorial_requested and not dateline_applied:
                    editorial_unresolved.append(state.path.name)

                records.append(
                    ExportRecord(
                        filename=state.path.name,
                        title=title,
                        description=shutterstock_description,
                        keywords=keywords,
                        adobe_category_id=adobe_category_id,
                        shutterstock_categories=shutterstock_categories,
                        editorial=bool(dateline_applied),
                    )
                )
            else:
                failures.append(state.path.name)
                self.table.item(row, COL_STATUS).setText("Write failed")

        if records and self.directory:
            export_adobe_stock_csv(records, self.directory / "adobe_stock.csv")
            export_shutterstock_csv(records, self.directory / "shutterstock.csv")

        if failures:
            QMessageBox.warning(
                self,
                "Some files failed",
                "Failed to write metadata for:\n" + "\n".join(failures),
            )
        elif editorial_unresolved:
            QMessageBox.warning(
                self,
                "Editorial dateline not applied",
                "No location or date could be resolved for the following "
                "photos, so they were exported without the editorial "
                "dateline:\n" + "\n".join(editorial_unresolved),
            )
        else:
            QMessageBox.information(
                self,
                "Done",
                f"Wrote metadata and exported CSVs for {len(records)} image(s).",
            )
