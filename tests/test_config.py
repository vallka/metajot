from metajot.config import AppConfig


def test_config_loads_defaults():
    config = AppConfig()
    assert config.ai.model == "gpt-5-mini"
