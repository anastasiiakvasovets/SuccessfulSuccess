"""`make llm-hello`: one question to the configured parser model, from your laptop.

Prints the answer, why it stopped and the token usage, so model access can be
checked before anything is deployed. PARSER_PROVIDER / PARSER_MODEL choose the
model, exactly as they do for the parser.
"""

from app.ai.providers import AnthropicApiProvider, AnthropicProvider
from app.config import settings

QUESTION = "In one sentence: what is an ISO week?"


def ask_anthropic(client, model: str) -> tuple[str, str, dict[str, int]]:
    """The Anthropic Messages API: served by Bedrock (bedrock-mantle) or by Anthropic."""
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        output_config={"effort": "low"},  # short, cheap answers
        messages=[{"role": "user", "content": QUESTION}],
    )
    text = next((b.text for b in msg.content if b.type == "text"), "")
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
    return text, msg.stop_reason, usage


def ask_converse(model: str) -> tuple[str, str, dict[str, int]]:
    """The Bedrock Converse API (bedrock-runtime): the same request shape for every model."""
    import boto3

    brt = boto3.client("bedrock-runtime", region_name=settings.parser_region)
    resp = brt.converse(
        modelId=model,
        messages=[{"role": "user", "content": [{"text": QUESTION}]}],
        inferenceConfig={"maxTokens": 200},
    )
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    usage = {
        "input_tokens": resp["usage"]["inputTokens"],
        "output_tokens": resp["usage"]["outputTokens"],
    }
    return text, resp["stopReason"], usage


def main() -> None:
    provider, model = settings.parser_provider, settings.parser_model
    print(f"provider={provider} model={model} region={settings.parser_region}")
    if provider == "anthropic":
        text, stop_reason, usage = ask_anthropic(AnthropicProvider._client(), model)
    elif provider == "anthropic_api":
        text, stop_reason, usage = ask_anthropic(AnthropicApiProvider._client(), model)
    elif provider == "converse":
        text, stop_reason, usage = ask_converse(model)
    else:
        text, stop_reason, usage = (
            "(fake provider: no model was called)",
            "end_turn",
            {
                "input_tokens": 0,
                "output_tokens": 0,
            },
        )
    print(text)
    print(f"stop_reason={stop_reason} usage={usage}")


if __name__ == "__main__":
    main()
