from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from metajot import config
from metajot.config import settings

# The key test is a single quick request - don't let it hang or retry.
TEST_TIMEOUT_SECONDS = 20


class SettingsDialog(QDialog):
    """Edits the OpenAI API key (saved to the OS credential store) and the
    [ai] settings (saved to the user config.toml)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        # Pre-filled only with the key stored by this dialog - one coming
        # from the env var or a config.toml file is managed there instead.
        self.api_key_edit.setText(config.get_stored_api_key() or "")
        show_key = QCheckBox("Show")
        show_key.toggled.connect(
            lambda on: self.api_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        test_btn = QPushButton("Test")
        test_btn.setToolTip("Check the key and model with a single quick API call.")
        test_btn.clicked.connect(self.test_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key_edit, 1)
        key_row.addWidget(show_key)
        key_row.addWidget(test_btn)
        form.addRow("OpenAI API key:", key_row)

        key_note = QLabel(self._key_source_note())
        key_note.setWordWrap(True)
        key_note.setStyleSheet("color: gray;")
        form.addRow("", key_note)

        self.model_edit = QLineEdit(settings.ai.model)
        self.model_edit.setToolTip("A vision-capable model, e.g. gpt-5-mini.")
        form.addRow("Model:", self.model_edit)

        self.base_url_edit = QLineEdit(settings.ai.base_url or "")
        self.base_url_edit.setPlaceholderText("Default (https://api.openai.com/v1)")
        self.base_url_edit.setToolTip(
            "Only needed for an OpenAI-compatible proxy or local endpoint."
        )
        form.addRow("Base URL:", self.base_url_edit)

        self.max_dim_spin = QSpinBox()
        self.max_dim_spin.setRange(256, 4096)
        self.max_dim_spin.setSingleStep(128)
        self.max_dim_spin.setSuffix(" px")
        self.max_dim_spin.setValue(settings.ai.max_image_dimension)
        self.max_dim_spin.setToolTip(
            "Photos are downscaled to this size on the long edge before being "
            "sent to the AI - larger is more detailed but slower and costlier."
        )
        form.addRow("Max image size:", self.max_dim_spin)

        layout.addLayout(form)

        location = QLabel(
            f"Settings file: {config.user_config_path()}\n"
            "The API key is stored in the system credential store, not in a file."
        )
        location.setStyleSheet("color: gray;")
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _key_source_note() -> str:
        source = settings.ai.api_key_source
        if source == "env":
            return (
                "Note: the OPENAI_API_KEY environment variable is set and takes "
                "priority over the key entered here."
            )
        if source == "config":
            return (
                "Currently using the api_key from a config.toml file. A key "
                "entered here takes priority over it."
            )
        return "Get a key at https://platform.openai.com/api-keys"

    def _effective_key(self) -> str:
        return self.api_key_edit.text().strip() or (settings.ai.api_key or "")

    def test_key(self) -> None:
        from openai import OpenAI

        api_key = self._effective_key()
        if not api_key:
            QMessageBox.warning(self, "No API key", "Enter an API key first.")
            return
        model = self.model_edit.text().strip() or config.DEFAULT_MODEL
        client = OpenAI(
            api_key=api_key,
            base_url=self.base_url_edit.text().strip() or None,
            timeout=TEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            client.models.retrieve(model)
        except Exception as e:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Test failed", f"{type(e).__name__}: {e}")
            return
        QGuiApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "Test passed", f"The key works and model {model} is available."
        )

    def save(self) -> None:
        try:
            config.set_stored_api_key(self.api_key_edit.text().strip() or None)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Could not save API key",
                f"The system credential store is unavailable: {e}\n\n"
                "You can set the OPENAI_API_KEY environment variable instead.",
            )
            return
        config.save_ai_settings(
            model=self.model_edit.text().strip() or config.DEFAULT_MODEL,
            base_url=self.base_url_edit.text().strip() or None,
            max_image_dimension=self.max_dim_spin.value(),
        )
        config.reload_settings()
        self.accept()
