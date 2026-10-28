"""Model providers for the agenda parser: one tool call, four ways to make it.

The parser asks the model to answer by calling one tool and validates what comes
back. Each provider hides its own request and message shapes behind the same
three methods, so the parser never sees an SDK type:

- `anthropic`: the Anthropic Messages API on Bedrock (bedrock-mantle), for the
  current Claude models. They accept no forced tool choice, so the system prompt
  asks for the tool.
- `converse`: the Bedrock Converse API (bedrock-runtime), e.g. Claude Haiku 4.5
  through the us. inference profile. Converse can force the tool, so it does.
- `anthropic_api`: the same Messages request as `anthropic`, sent to the Claude
  API directly with an API key (ANTHROPIC_API_KEY locally, an SSM SecureString
  in Lambda). The fallback while Bedrock is blocked for the account.
- `fake`: no model at all. It splits the text into lines, so the feature can be
  built and deployed before Bedrock access works.

Throttling from any of them is raised as ModelBusyError (the function URL
answers 429 with it).
"""

import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Protocol

from app.config import settings

MAX_TOKENS = 4096


class ModelBusyError(Exception):
    """The model service throttled the request even after the SDK's retries."""


@dataclass
class ToolCall:
    """One model response: the tool's input, or None when the model did not call it."""

    input: dict[str, Any] | None
    stop_reason: str
    input_tokens: int
    output_tokens: int
    # What the provider needs to send this turn back with an error (retry).
    tool_use_id: str | None = None
    assistant_message: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    def user_message(self, text: str) -> dict[str, Any]: ...

    def call(self, system: str, tool: dict[str, Any], messages: list[dict[str, Any]]) -> ToolCall:
        """`tool` is in the Anthropic shape: name, description, input_schema."""
        ...

    def error_reply(self, call: ToolCall, error: str) -> list[dict[str, Any]]:
        """The turns that show the model its invalid tool input, for one more try."""
        ...


class AnthropicProvider:
    def __init__(self, model: str) -> None:
        self.model = model

    @staticmethod
    @cache
    def _client():
        from anthropic import AnthropicBedrockMantle

        return AnthropicBedrockMantle(aws_region=settings.parser_region)

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}

    def call(self, system: str, tool: dict[str, Any], messages: list[dict[str, Any]]) -> ToolCall:
        import anthropic

        try:
            msg = self._client().messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                output_config={"effort": "low"},
                system=system,
                tools=[tool],
                messages=messages,
            )
        except anthropic.RateLimitError as exc:
            raise ModelBusyError(str(exc)) from exc
        block = next((b for b in msg.content if b.type == "tool_use"), None)
        return ToolCall(
            input=block.input if block is not None else None,
            stop_reason=msg.stop_reason or "",
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            tool_use_id=block.id if block is not None else None,
            # Every block goes back unchanged, thinking blocks included.
            assistant_message={"role": "assistant", "content": msg.content},
        )

    def error_reply(self, call: ToolCall, error: str) -> list[dict[str, Any]]:
        result = {
            "type": "tool_result",
            "tool_use_id": call.tool_use_id,
            "content": error,
            "is_error": True,
        }
        return [call.assistant_message, {"role": "user", "content": [result]}]


def anthropic_api_key() -> str | None:
    """The Claude API key from SSM when ANTHROPIC_API_KEY_PARAMETER names one (Lambda).

    None lets the SDK read ANTHROPIC_API_KEY from the environment (local runs).
    The key is never logged; callers cache the client that holds it.
    """
    if not settings.anthropic_api_key_parameter:
        return None
    import boto3

    ssm = boto3.client("ssm", region_name=settings.parser_region)
    response = ssm.get_parameter(Name=settings.anthropic_api_key_parameter, WithDecryption=True)
    return response["Parameter"]["Value"]


class AnthropicApiProvider(AnthropicProvider):
    """The same Messages request, sent to the Claude API directly instead of Bedrock."""

    @staticmethod
    @cache
    def _client():
        from anthropic import Anthropic

        return Anthropic(api_key=anthropic_api_key())


class ConverseProvider:
    # Converse error codes that mean "too many requests now", not "you made a mistake".
    BUSY_CODES = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"}

    def __init__(self, model: str) -> None:
        self.model = model

    @staticmethod
    @cache
    def _client():
        import boto3

        return boto3.client("bedrock-runtime", region_name=settings.parser_region)

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "content": [{"text": text}]}

    def call(self, system: str, tool: dict[str, Any], messages: list[dict[str, Any]]) -> ToolCall:
        from botocore.exceptions import ClientError

        spec = {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": {"json": tool["input_schema"]},
        }
        try:
            resp = self._client().converse(
                modelId=self.model,
                system=[{"text": system}],
                messages=messages,
                toolConfig={
                    "tools": [{"toolSpec": spec}],
                    "toolChoice": {"tool": {"name": spec["name"]}},
                },
                inferenceConfig={"maxTokens": MAX_TOKENS},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in self.BUSY_CODES:
                raise ModelBusyError(str(exc)) from exc
            raise
        message = resp["output"]["message"]
        use = next((b["toolUse"] for b in message["content"] if "toolUse" in b), None)
        return ToolCall(
            input=use["input"] if use is not None else None,
            stop_reason=resp["stopReason"],
            input_tokens=resp["usage"]["inputTokens"],
            output_tokens=resp["usage"]["outputTokens"],
            tool_use_id=use["toolUseId"] if use is not None else None,
            assistant_message=message,
        )

    def error_reply(self, call: ToolCall, error: str) -> list[dict[str, Any]]:
        result = {
            "toolResult": {
                "toolUseId": call.tool_use_id,
                "content": [{"text": error}],
                "status": "error",
            }
        }
        return [call.assistant_message, {"role": "user", "content": [result]}]


class FakeProvider:
    """Turns each line (or numbered point) of the pasted text into an agenda item."""

    _pasted = re.compile(r"<pasted_text>\n(.*)\n</pasted_text>", re.S)
    _points = re.compile(r"(?:^|\s)\d+[).]\s+")
    _minutes = re.compile(r"(\d{1,3})\s*(?:хв|min|minutes|m)\b", re.I)

    def __init__(self, model: str) -> None:
        self.model = model

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}

    def call(self, system: str, tool: dict[str, Any], messages: list[dict[str, Any]]) -> ToolCall:
        found = self._pasted.search(messages[0]["content"])
        text = found.group(1) if found else ""
        pieces = [p.strip(" .;—-") for line in text.splitlines() for p in self._points.split(line)]
        items = []
        for piece in filter(None, pieces):
            minutes = self._minutes.search(piece)
            items.append(
                {"topic": piece[:200], "minutes": int(minutes.group(1)) if minutes else None}
            )
        cyrillic = sum("а" <= ch.lower() <= "я" or ch in "іїєґ" for ch in text)
        return ToolCall(
            input={"items": items, "language": "uk" if cyrillic > len(text) / 4 else "en"},
            stop_reason="tool_use",
            input_tokens=0,
            output_tokens=0,
        )

    def error_reply(self, call: ToolCall, error: str) -> list[dict[str, Any]]:
        return []


PROVIDERS: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "converse": ConverseProvider,
    "anthropic_api": AnthropicApiProvider,
    "fake": FakeProvider,
}


def warm_up() -> None:
    """Create the configured provider's client now, e.g. in Lambda's init phase,
    so fetching the Claude API key from SSM does not slow down the first parse."""
    if settings.parser_provider == "anthropic_api":
        AnthropicApiProvider._client()


def get_provider() -> Provider:
    """The provider and model chosen by PARSER_PROVIDER and PARSER_MODEL."""
    return PROVIDERS[settings.parser_provider](settings.parser_model)
