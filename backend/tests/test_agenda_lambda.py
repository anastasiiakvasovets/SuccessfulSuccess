"""The agenda parser's Lambda handler behind its function URL (Lab 6).

Tokens are real RS256 tokens for the test pool (tests/tokens.py); the model is
the fake provider, or parse_agenda is replaced to reach the error paths.
"""

import base64
import json
import logging

import pytest

from app.ai import agenda_lambda
from app.ai.agenda import AgendaParseError
from app.ai.providers import ModelBusyError
from app.config import settings
from tests.tokens import make_id_token, make_token

BODY = {
    "text": "1) Pricing — Olena, 15 min\n2) Feedback",
    "today": "2026-10-27",
    "tz": "Europe/Kyiv",
}


@pytest.fixture(autouse=True)
def fake_model(monkeypatch, verifier):
    monkeypatch.setattr(settings, "parser_provider", "fake")
    monkeypatch.setattr(agenda_lambda, "get_verifier", lambda: verifier)


@pytest.fixture
def bearer(private_key) -> dict:
    return {"authorization": f"Bearer {make_token(private_key)}"}


def invoke(body=BODY, headers=None, base64_body=False):
    raw = body if isinstance(body, str) else json.dumps(body)
    event = {"headers": headers or {}, "body": raw, "isBase64Encoded": base64_body}
    if base64_body:
        event["body"] = base64.b64encode(raw.encode()).decode()
    response = agenda_lambda.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def log_lines(caplog) -> list[dict]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "meetings.ai" and r.getMessage().startswith("{")
    ]


@pytest.fixture(autouse=True)
def capture_logs(caplog):
    caplog.set_level(logging.INFO, logger="meetings.ai")


# --- who may call it -------------------------------------------------------------


def test_no_token_is_401():
    status, body = invoke()

    assert status == 401
    assert body["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer not-a-jwt"])
def test_malformed_authorization_is_401(header):
    status, _ = invoke(headers={"authorization": header})

    assert status == 401


def test_expired_token_is_401(private_key):
    token = make_token(private_key, exp=1_700_000_000, iat=1_699_996_400)

    status, body = invoke(headers={"authorization": f"Bearer {token}"})

    assert status == 401
    assert "expired" in body["error"]["message"]


def test_id_token_is_refused(private_key):
    status, _ = invoke(headers={"authorization": f"Bearer {make_id_token(private_key)}"})

    assert status == 401


def test_long_text_from_a_stranger_is_still_401():
    status, _ = invoke({**BODY, "text": "x" * 20_000})

    assert status == 401


def test_missing_auth_config_is_503(monkeypatch):
    from app.auth import AuthNotConfiguredError

    def not_configured():
        raise AuthNotConfiguredError()

    monkeypatch.setattr(agenda_lambda, "get_verifier", not_configured)

    status, _ = invoke(headers={"authorization": "Bearer x"})

    assert status == 503


# --- what it accepts ---------------------------------------------------------------


def test_text_over_the_limit_is_413_before_any_model_call(bearer, monkeypatch):
    def must_not_run(*_):
        raise AssertionError("the model was called")

    monkeypatch.setattr(agenda_lambda, "parse_agenda", must_not_run)

    status, body = invoke({**BODY, "text": "x" * (settings.parser_max_chars + 1)}, bearer)

    assert status == 413
    assert body["error"]["code"] == "payload_too_large"


def test_text_at_the_limit_is_accepted(bearer):
    status, _ = invoke({**BODY, "text": "x" * settings.parser_max_chars}, bearer)

    assert status == 200


@pytest.mark.parametrize(
    "body",
    [
        "{not json",
        [],
        {"today": "2026-10-27", "tz": "Europe/Kyiv"},
        {**BODY, "text": ""},
        {**BODY, "today": "27.10.2026"},
        {**BODY, "tz": "Mars/Olympus"},
    ],
    ids=["not-json", "not-an-object", "no-text", "empty-text", "bad-date", "bad-tz"],
)
def test_bad_body_is_400(bearer, body):
    status, response = invoke(body, bearer)

    assert status == 400
    assert response["error"]["code"] == "invalid_request"


def test_base64_body_is_decoded(bearer):
    status, _ = invoke(BODY, bearer, base64_body=True)

    assert status == 200


# --- what it answers ------------------------------------------------------------------


def test_parse_returns_the_agenda_and_logs_one_line(bearer, caplog):
    status, body = invoke(BODY, bearer)

    assert status == 200
    assert [item["topic"] for item in body["agenda"]["items"]] == [
        "Pricing — Olena, 15 min",
        "Feedback",
    ]
    assert body["model"] == "fake"
    assert body["prompt_version"] == "agenda-v1"
    [line] = log_lines(caplog)
    assert line["event"] == "agenda_parsed"
    assert line["user"] == "user-123"
    assert line["model"] == "fake"
    assert line["chars"] == len(BODY["text"])
    assert {"input_tokens", "output_tokens", "latency_ms", "cost_usd"} <= line.keys()
    assert line["cost_usd"] == 0.0


def test_no_agenda_is_422_and_its_tokens_are_logged(bearer, caplog, monkeypatch):
    def no_agenda(*_):
        raise AgendaParseError(
            "no agenda returned (stop_reason=end_turn)", {"input_tokens": 900, "output_tokens": 40}
        )

    monkeypatch.setattr(agenda_lambda, "parse_agenda", no_agenda)
    monkeypatch.setattr(settings, "parser_provider", "anthropic")
    monkeypatch.setattr(settings, "parser_model", "anthropic.claude-opus-5-5")

    status, body = invoke(BODY, bearer)

    assert status == 422
    assert body["error"]["code"] == "no_agenda"
    [line] = log_lines(caplog)
    assert line["event"] == "agenda_parse_failed"
    assert (line["input_tokens"], line["output_tokens"]) == (900, 40)
    assert line["cost_usd"] == 0.0044  # 900 × $4/M + 40 × $20/M: failed parses cost too


def test_throttling_is_429(bearer, monkeypatch):
    def busy(*_):
        raise ModelBusyError("ThrottlingException")

    monkeypatch.setattr(agenda_lambda, "parse_agenda", busy)

    status, body = invoke(BODY, bearer)

    assert status == 429
    assert body["error"]["code"] == "model_busy"


def test_model_failure_is_503_without_leaking_the_error(bearer, caplog, monkeypatch):
    def denied(*_):
        raise RuntimeError("403 anthropic.claude-opus-5-5 is not available for this account")

    monkeypatch.setattr(agenda_lambda, "parse_agenda", denied)

    status, body = invoke(BODY, bearer)

    assert status == 503
    assert body["error"]["code"] == "model_unavailable"
    assert "403" not in body["error"]["message"]
    assert log_lines(caplog)[-1]["status"] == 503


def test_response_sets_no_cors_headers(bearer):
    response = agenda_lambda.handler(
        {"headers": bearer, "body": json.dumps(BODY), "isBase64Encoded": False}, None
    )

    # The function URL adds CORS; a second copy from the handler would break it.
    assert not any(name.lower().startswith("access-control") for name in response["headers"])
