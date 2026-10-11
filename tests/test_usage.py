from types import SimpleNamespace

import pytest

from metajot.config import load_config
from metajot.usage import (
    MODEL_PRICES,
    ModelPrice,
    TokenUsage,
    estimate_cost,
    format_cost,
    price_for_model,
    usage_from_response,
)


def test_price_for_model_matches_longest_prefix():
    assert price_for_model("gpt-5-mini") == MODEL_PRICES["gpt-5-mini"]
    assert price_for_model("gpt-5-mini-2025-08-07") == MODEL_PRICES["gpt-5-mini"]
    assert price_for_model("gpt-5") == MODEL_PRICES["gpt-5"]
    assert price_for_model("gpt-4o-mini") == MODEL_PRICES["gpt-4o-mini"]


def test_price_for_model_unknown():
    assert price_for_model("llava:13b") is None
    # A prefix only counts up to a "-", so gpt-50 isn't priced as gpt-5.
    assert price_for_model("gpt-50") is None


def test_estimate_cost_prices_cached_input_separately():
    usage = TokenUsage(
        input_tokens=2_000_000, cached_input_tokens=1_000_000, output_tokens=500_000
    )
    price = ModelPrice(input=1.0, cached_input=0.1, output=4.0)
    assert estimate_cost(usage, price) == pytest.approx(1.0 + 0.1 + 2.0)
    assert estimate_cost(usage, None) is None


def test_token_usage_sum():
    a = TokenUsage(input_tokens=100, output_tokens=50, reasoning_tokens=20, cost=0.01)
    b = TokenUsage(
        input_tokens=200, cached_input_tokens=10, output_tokens=60, cost=0.02
    )
    total = a + b
    assert total.input_tokens == 300
    assert total.cached_input_tokens == 10
    assert total.output_tokens == 110
    assert total.reasoning_tokens == 20
    assert total.total_tokens == 410
    assert total.cost == pytest.approx(0.03)
    assert total.requests == 2


def test_token_usage_sum_cost_unknown_if_any_unknown():
    assert (TokenUsage(cost=0.01) + TokenUsage(cost=None)).cost is None


def test_usage_from_response():
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=2100,
            completion_tokens=1500,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=900),
        )
    )
    usage = usage_from_response(response, MODEL_PRICES["gpt-5-mini"])
    assert usage.input_tokens == 2100
    assert usage.output_tokens == 1500
    assert usage.reasoning_tokens == 900
    assert usage.cost == pytest.approx((2100 * 0.25 + 1500 * 2.00) / 1_000_000)


def test_usage_from_response_without_details():
    """OpenAI-compatible servers may leave out the detail fields."""
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            prompt_tokens_details=None,
            completion_tokens_details=None,
        )
    )
    usage = usage_from_response(response, None)
    assert (usage.input_tokens, usage.output_tokens, usage.cost) == (10, 5, None)


def test_format_cost():
    assert format_cost(0.0031) == "$0.0031"
    assert format_cost(1.234) == "$1.23"


def test_short_text():
    usage = TokenUsage(input_tokens=2000, output_tokens=1412, cost=0.0041)
    assert usage.short_text() == "3,412 tokens · ~$0.0041"
    assert TokenUsage(input_tokens=10, cost=None).short_text() == "10 tokens"


@pytest.fixture
def no_keyring(monkeypatch):
    """Keeps load_config() away from the real credential store."""
    monkeypatch.setattr("metajot.config.get_stored_api_key", lambda: None)


def test_config_price_override(tmp_path, no_keyring):
    user = tmp_path / "config.toml"
    user.write_text(
        "[ai]\ninput_price = 0.5\noutput_price = 3\n", encoding="utf-8"
    )
    config = load_config(project_config_path=tmp_path / "none.toml", user_path=user)
    assert config.ai.price_override == ModelPrice(
        input=0.5, cached_input=0.5, output=3.0
    )


def test_config_no_price_override_by_default(tmp_path, no_keyring):
    config = load_config(
        project_config_path=tmp_path / "none.toml", user_path=tmp_path / "none2.toml"
    )
    assert config.ai.price_override is None
