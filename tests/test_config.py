import keyring
import pytest
from keyring.backend import KeyringBackend

from metajot import config
from metajot.config import AppConfig


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.passwords:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.passwords[(service, username)]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keeps tests away from the real credential store, user config folder,
    project config.toml and OPENAI_API_KEY."""
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    monkeypatch.setenv("METAJOT_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    keyring.set_keyring(previous)


def test_config_loads_defaults():
    config_ = AppConfig()
    assert config_.ai.model == "gpt-5-mini"
    # The default prompt ships with the package, not just in config.toml.
    assert "stock photography" in config_.prompts.system_prompt


def test_load_config_without_any_files_uses_defaults():
    loaded = config.load_config()
    assert loaded.ai.model == config.DEFAULT_MODEL
    assert loaded.ai.api_key is None
    assert loaded.prompts.system_prompt == config.default_system_prompt()


def test_user_config_overrides_project_config(isolated):
    (isolated / "config.toml").write_text(
        '[ai]\nmodel = "project-model"\nmax_image_dimension = 800\n'
    )
    config.save_ai_settings(model="user-model", base_url=None, max_image_dimension=900)

    loaded = config.load_config()
    assert loaded.ai.model == "user-model"
    assert loaded.ai.max_image_dimension == 900


def test_save_ai_settings_keeps_other_sections(isolated):
    user_path = config.user_config_path()
    user_path.parent.mkdir(parents=True)
    user_path.write_text('[prompts]\nsystem_prompt = "Custom prompt"\n')

    config.save_ai_settings(
        model="m", base_url="http://localhost:1234/v1", max_image_dimension=512
    )

    loaded = config.load_config()
    assert loaded.prompts.system_prompt == "Custom prompt"
    assert loaded.ai.base_url == "http://localhost:1234/v1"
    assert "api_key" not in user_path.read_text()


def test_api_key_precedence(isolated, monkeypatch):
    (isolated / "config.toml").write_text('[ai]\napi_key = "file-key"\n')
    assert config.load_config().ai.api_key_source == "config"

    config.set_stored_api_key("stored-key")
    loaded = config.load_config()
    assert (loaded.ai.api_key, loaded.ai.api_key_source) == ("stored-key", "keyring")

    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    loaded = config.load_config()
    assert (loaded.ai.api_key, loaded.ai.api_key_source) == ("env-key", "env")


def test_clearing_stored_api_key():
    config.set_stored_api_key("stored-key")
    config.set_stored_api_key(None)
    assert config.get_stored_api_key() is None
    config.set_stored_api_key(None)  # clearing twice is fine


def test_state_round_trip():
    assert config.load_state() == {}
    config.save_state(recent_folders=["a"])
    config.save_state(other=1)
    assert config.load_state() == {"recent_folders": ["a"], "other": 1}
