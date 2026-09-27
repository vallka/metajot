"""Settings, API key and app state storage.

- The API key lives in the OS credential store (Windows Credential Manager,
  macOS Keychain, Linux Secret Service) via `keyring`, never in a file
  written by MetaJot.
- Other settings live in a per-user config.toml (see user_config_dir()),
  editable via the Settings dialog or by hand.
- UI state (e.g. the last opened folder) lives in state.json next to it.
- A config.toml in the current working directory (the original, pre-GUI
  setup) is still read as a lower-priority fallback, so existing setups keep
  working.

Precedence for each setting: built-in default < ./config.toml < user
config.toml. For the API key: OPENAI_API_KEY env var > credential store >
config.toml files.
"""

import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import keyring
import tomli_w

APP_NAME = "MetaJot"
KEYRING_SERVICE = "MetaJot"
KEYRING_USERNAME = "openai_api_key"

# The original project-root config.toml, resolved against the current
# working directory at runtime.
PROJECT_CONFIG_PATH = Path("config.toml")

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_MAX_IMAGE_DIMENSION = 1024
DEFAULT_PROMPT_PATH = Path(__file__).parent / "data" / "system_prompt.txt"


def user_config_dir() -> Path:
    """Per-user folder for config.toml and state.json. METAJOT_CONFIG_DIR
    overrides it (used by tests)."""
    if override := os.getenv("METAJOT_CONFIG_DIR"):
        return Path(override)
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME.lower()


def user_config_path() -> Path:
    return user_config_dir() / "config.toml"


def state_path() -> Path:
    return user_config_dir() / "state.json"


def default_system_prompt() -> str:
    return DEFAULT_PROMPT_PATH.read_text(encoding="utf-8").strip()


@dataclass
class AIConfig:
    model: str = DEFAULT_MODEL
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    # Where api_key came from: "env", "keyring", "config" or None.
    api_key_source: Optional[str] = None
    max_image_dimension: int = DEFAULT_MAX_IMAGE_DIMENSION


@dataclass
class PromptsConfig:
    system_prompt: str = field(default_factory=default_system_prompt)


@dataclass
class AppConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def get_stored_api_key() -> Optional[str]:
    """The API key saved in the OS credential store, if any."""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception as e:
        print(f"Warning: Failed to read API key from credential store: {e}")
        return None


def set_stored_api_key(api_key: Optional[str]) -> None:
    """Saves the API key to the OS credential store, or removes it if empty.
    Raises if the credential store is unavailable."""
    if api_key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass  # nothing stored


def load_config(
    project_config_path: Path = PROJECT_CONFIG_PATH,
    user_path: Optional[Path] = None,
) -> AppConfig:
    """Loads settings, layering the user config.toml over ./config.toml over
    the built-in defaults, and resolves the API key (see module docstring)."""
    user_path = user_path or user_config_path()
    layers = [_read_toml(project_config_path), _read_toml(user_path)]

    ai_data: dict[str, Any] = {}
    prompts_data: dict[str, Any] = {}
    for layer in layers:
        ai_data.update(layer.get("ai", {}))
        prompts_data.update(layer.get("prompts", {}))

    app_config = AppConfig()
    app_config.ai = AIConfig(
        model=ai_data.get("model") or DEFAULT_MODEL,
        base_url=ai_data.get("base_url") or None,
        max_image_dimension=int(
            ai_data.get("max_image_dimension") or DEFAULT_MAX_IMAGE_DIMENSION
        ),
    )

    if env_key := os.getenv("OPENAI_API_KEY"):
        app_config.ai.api_key, app_config.ai.api_key_source = env_key, "env"
    elif stored_key := get_stored_api_key():
        app_config.ai.api_key, app_config.ai.api_key_source = stored_key, "keyring"
    elif file_key := ai_data.get("api_key"):
        app_config.ai.api_key, app_config.ai.api_key_source = file_key, "config"

    if prompt := (prompts_data.get("system_prompt") or "").strip():
        app_config.prompts.system_prompt = prompt

    return app_config


def save_ai_settings(
    model: str,
    base_url: Optional[str],
    max_image_dimension: int,
    user_path: Optional[Path] = None,
) -> None:
    """Writes the [ai] settings to the user config.toml, keeping any other
    content already in it (e.g. a [prompts] override). The API key is never
    written here - see set_stored_api_key()."""
    user_path = user_path or user_config_path()
    data = _read_toml(user_path)
    ai = data.setdefault("ai", {})
    ai["model"] = model
    if base_url:
        ai["base_url"] = base_url
    else:
        ai.pop("base_url", None)
    ai["max_image_dimension"] = max_image_dimension

    user_path.parent.mkdir(parents=True, exist_ok=True)
    with open(user_path, "wb") as f:
        tomli_w.dump(data, f)


def reload_settings() -> None:
    """Re-reads all settings into the shared `settings` object in place, so
    modules holding a reference to it (e.g. ai.py) see the new values."""
    fresh = load_config()
    settings.ai = fresh.ai
    settings.prompts = fresh.prompts


def load_state() -> dict[str, Any]:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(**values: Any) -> None:
    """Merges values into state.json (best effort - UI state isn't critical)."""
    state = load_state()
    state.update(values)
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"Warning: Failed to save app state: {e}")


# Global configuration instance, initialized on import
settings = load_config()
