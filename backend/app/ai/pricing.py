"""What one parse costs, from the token usage the model reports."""

# $ per 1M tokens: (input, output). Anthropic's list prices from Lab 6, Part 1;
# Bedrock's own price page is what the bill uses. Claude Haiku 4.5 is reached
# through the us. cross-region inference profile on the Converse API.
PRICES: dict[str, tuple[float, float]] = {
    "anthropic.claude-opus-5-5": (4.00, 20.00),
    "anthropic.claude-sonnet-5-5": (2.00, 10.00),
    "anthropic.claude-haiku-5-5": (0.10, 0.50),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    # The Claude API directly (PARSER_PROVIDER=anthropic_api): Anthropic's own prices.
    # Haiku 5.5's price is for prompts up to 100K tokens; a pasted agenda is far below.
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    # PARSER_PROVIDER=fake calls no model.
    "fake": (0.0, 0.0),
}


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    """The price of `usage` in dollars; None for a model without a known price."""
    if model not in PRICES:
        return None
    input_price, output_price = PRICES[model]
    cost = usage["input_tokens"] * input_price + usage["output_tokens"] * output_price
    return round(cost / 1_000_000, 6)
