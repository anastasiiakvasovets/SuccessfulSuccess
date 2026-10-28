"""AWS Lambda entry point of the agenda parser (the backend image, another handler).

Behind its own public function URL and outside the VPC: it needs no database,
only Bedrock and Cognito's signing keys, both reached over the internet. Every
call costs money, so it answers only signed-in users (the same Cognito access
tokens as the API) and refuses long text before any model is called. It never
writes anything: the browser saves the agenda through the API.

POST {"text": "...", "today": "2026-10-27", "tz": "Europe/Kyiv"}
  200 {"agenda": {...}, "model": "...", "prompt_version": "agenda-v1"}
  400 bad request body, 401 no or bad token, 413 text too long,
  422 no agenda in the text, 429 the model is busy, 503 the model is unavailable.
Errors use the API's envelope: {"error": {"code", "message", "details"}}.
CORS is configured on the function URL, not here.
"""

import asyncio
import base64
import json
import logging
import time
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.ai.agenda import PROMPT_VERSION, AgendaParseError, parse_agenda
from app.ai.pricing import cost_usd
from app.ai.providers import ModelBusyError, warm_up
from app.auth import AuthError, AuthNotConfiguredError, CurrentUser, get_verifier
from app.config import settings

log = logging.getLogger("meetings.ai")
log.setLevel(settings.log_level.upper())

# Cold start: load the Claude API key from SSM once, and keep the client that
# holds it. A failure must not stop the function (a 401 needs no model), so it
# is logged — the error never contains the key — and retried on the first parse.
try:
    warm_up()
except Exception:
    log.exception("agenda parser: could not create the model client at start")


class ParseRequest(BaseModel):
    text: str = Field(min_length=1)
    # The user's "Monday" is in the user's time zone, not the function's (UTC).
    today: date
    tz: str

    @field_validator("tz")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("must be an IANA time zone, e.g. Europe/Kyiv") from exc
        return value


def respond(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def error(status: int, code: str, message: str) -> dict[str, Any]:
    return respond(status, {"error": {"code": code, "message": message, "details": []}})


def verify_cognito_token(authorization: str) -> CurrentUser:
    """The caller of a "Bearer <access token>" header; AuthError for anything else."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Sign in to continue.")
    # No COGNITO_JWKS here: outside the VPC the verifier fetches the keys itself.
    return asyncio.run(get_verifier().verify(token))


def request_body(event: dict[str, Any]) -> Any:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    return json.loads(body)


def log_parse(user: str, status: int, started: float, chars: int, usage: dict[str, int]) -> None:
    """One JSON line per parse: what it cost, and enough to compare models and prompts."""
    log.info(
        json.dumps(
            {
                "event": "agenda_parsed" if status == 200 else "agenda_parse_failed",
                "status": status,
                "user": user,
                "provider": settings.parser_provider,
                "model": settings.parser_model_id,
                "prompt_version": PROMPT_VERSION,
                "chars": chars,
                **usage,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "cost_usd": cost_usd(settings.parser_model_id, usage),
            }
        )
    )


def handler(event, context):
    headers = event.get("headers") or {}  # function URLs lower-case header names
    try:
        user = verify_cognito_token(headers.get("authorization", ""))
    except AuthError as exc:
        return error(401, "unauthorized", str(exc))
    except AuthNotConfiguredError:
        log.error("agenda parser: COGNITO_USER_POOL_ID / COGNITO_CLIENT_ID are not set")
        return error(503, "service_unavailable", "Sign-in is not configured.")

    try:
        raw = request_body(event)
    except (ValueError, UnicodeDecodeError):
        return error(400, "invalid_request", "The body must be JSON.")
    # Checked before anything else about the body, and before any model call.
    if isinstance(raw, dict) and len(str(raw.get("text", ""))) > settings.parser_max_chars:
        return error(
            413,
            "payload_too_large",
            f"The text is longer than {settings.parser_max_chars:,} characters.",
        )
    try:
        body = ParseRequest.model_validate(raw)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, e["loc"])) or "body" for e in exc.errors())
        return error(400, "invalid_request", f"Invalid request: {fields}.")

    started = time.monotonic()
    no_usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        agenda, usage = parse_agenda(body.text, body.today, body.tz)
    except AgendaParseError as exc:
        log_parse(user.sub, 422, started, len(body.text), exc.usage)
        return error(422, "no_agenda", f"Could not find an agenda in the text: {exc}.")
    except ModelBusyError:
        log_parse(user.sub, 429, started, len(body.text), no_usage)
        return error(429, "model_busy", "The model is busy. Try again in a minute.")
    except Exception:  # access denied, model not found, network: the user types it instead
        log.exception("agenda parser: the model call failed")
        log_parse(user.sub, 503, started, len(body.text), no_usage)
        return error(503, "model_unavailable", "The agenda parser is unavailable right now.")

    log_parse(user.sub, 200, started, len(body.text), usage)
    return respond(
        200,
        {
            "agenda": agenda.model_dump(mode="json"),
            "model": settings.parser_model_id,
            "prompt_version": PROMPT_VERSION,
        },
    )
