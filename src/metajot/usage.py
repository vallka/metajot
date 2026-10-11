"""Token usage of AI requests, and its estimated cost.

Costs are estimates from list prices per 1M tokens: actual billing can differ
(e.g. free tokens for sharing data with OpenAI, batch/flex discounts, or price
changes). Prices for a model not listed here can be set in config.toml - see
AIConfig.price_override.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens."""

    input: float
    cached_input: float
    output: float


# OpenAI list prices (standard tier). Matched by longest prefix, so dated
# snapshots like "gpt-5-mini-2025-08-07" use their base model's price.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5": ModelPrice(1.25, 0.125, 10.00),
    "gpt-5-mini": ModelPrice(0.25, 0.025, 2.00),
    "gpt-5-nano": ModelPrice(0.05, 0.005, 0.40),
    "gpt-4.1": ModelPrice(2.00, 0.50, 8.00),
    "gpt-4.1-mini": ModelPrice(0.40, 0.10, 1.60),
    "gpt-4.1-nano": ModelPrice(0.10, 0.025, 0.40),
    "gpt-4o": ModelPrice(2.50, 1.25, 10.00),
    "gpt-4o-mini": ModelPrice(0.15, 0.075, 0.60),
}


def price_for_model(model: str) -> Optional[ModelPrice]:
    model = model.lower()
    matches = [
        name
        for name in MODEL_PRICES
        if model == name or model.startswith(name + "-")
    ]
    return MODEL_PRICES[max(matches, key=len)] if matches else None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    # Part of input_tokens served from OpenAI's prompt cache (cheaper).
    cached_input_tokens: int = 0
    output_tokens: int = 0
    # Part of output_tokens spent on the model's hidden reasoning.
    reasoning_tokens: int = 0
    # Estimated USD, or None if the model's price is unknown.
    cost: Optional[float] = None
    # Number of AI requests this usage is the sum of.
    requests: int = 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cost=(
                None
                if self.cost is None or other.cost is None
                else self.cost + other.cost
            ),
            requests=self.requests + other.requests,
        )

    def short_text(self) -> str:
        """e.g. "3,412 tokens · ~$0.0041" """
        text = f"{self.total_tokens:,} tokens"
        if self.cost is not None:
            text += f" · ~{format_cost(self.cost)}"
        return text

    def details_text(self) -> str:
        """Multi-line breakdown, for tooltips and the run summary."""
        lines = [
            f"Input: {self.input_tokens:,} tokens"
            + (
                f" ({self.cached_input_tokens:,} cached)"
                if self.cached_input_tokens
                else ""
            ),
            f"Output: {self.output_tokens:,} tokens"
            + (
                f" (incl. {self.reasoning_tokens:,} reasoning)"
                if self.reasoning_tokens
                else ""
            ),
            f"Total: {self.total_tokens:,} tokens",
        ]
        if self.cost is not None:
            lines.append(f"Estimated cost: {format_cost(self.cost)}")
        else:
            lines.append("Estimated cost: unknown (no price for this model)")
        return "\n".join(lines)


def format_cost(cost: float) -> str:
    # Per-photo costs are fractions of a cent, so show enough digits to see.
    return f"${cost:.4f}" if cost < 0.10 else f"${cost:.2f}"


def estimate_cost(
    usage: TokenUsage, price: Optional[ModelPrice]
) -> Optional[float]:
    if price is None:
        return None
    uncached = usage.input_tokens - usage.cached_input_tokens
    return (
        uncached * price.input
        + usage.cached_input_tokens * price.cached_input
        + usage.output_tokens * price.output
    ) / 1_000_000


def usage_from_response(response, price: Optional[ModelPrice]) -> TokenUsage:
    """Builds TokenUsage from an OpenAI chat completion's `usage` (whose
    detail fields may be missing on OpenAI-compatible servers)."""
    raw = getattr(response, "usage", None)
    if raw is None:
        return TokenUsage(cost=None)
    prompt_details = getattr(raw, "prompt_tokens_details", None)
    completion_details = getattr(raw, "completion_tokens_details", None)
    usage = TokenUsage(
        input_tokens=raw.prompt_tokens or 0,
        cached_input_tokens=getattr(prompt_details, "cached_tokens", None) or 0,
        output_tokens=raw.completion_tokens or 0,
        reasoning_tokens=getattr(completion_details, "reasoning_tokens", None) or 0,
    )
    usage.cost = estimate_cost(usage, price)
    return usage
