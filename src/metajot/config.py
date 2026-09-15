import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Determine the configuration path relative to the current working directory
CONFIG_PATH = Path("config.toml")


@dataclass
class AIConfig:
    model: str = "gpt-5-mini"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    max_image_dimension: int = 1024


@dataclass
class PromptsConfig:
    system_prompt: str = ""


@dataclass
class AppConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)


def load_config(config_path: Path = CONFIG_PATH) -> AppConfig:
    """Loads and validates the application configuration from config.toml."""
    app_config = AppConfig()

    if not config_path.exists():
        return app_config

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    ai_data = data.get("ai", {})
    prompts_data = data.get("prompts", {})

    # Use environment variable as priority for API Key to avoid saving secrets to disk
    api_key = os.getenv("OPENAI_API_KEY") or ai_data.get("api_key")

    app_config.ai = AIConfig(
        model=ai_data.get("model", "gpt-5-mini"),
        base_url=ai_data.get("base_url"),
        api_key=api_key,
        max_image_dimension=ai_data.get("max_image_dimension", 1024),
    )

    app_config.prompts = PromptsConfig(
        system_prompt=prompts_data.get("system_prompt", "")
    )

    return app_config


# Global configuration instance, initialized on import
settings = load_config()
