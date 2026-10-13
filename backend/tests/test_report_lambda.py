"""The report builder's event handling. No AWS: the S3 call is never reached."""

import logging
from datetime import datetime

import pytest

from app.config import settings
from app.reports.lambda_handler import (
    delivery_of,
    detect_trigger,
    handler,
    payload_of,
    resolve_week,
)

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=settings.tz)  # a Tuesday in 2026-W42


def sqs_event(body: str, receive_count: int = 1, message_id: str = "m-1") -> dict:
    """The shape the SQS event source mapping invokes the builder with (batch size 1)."""
    return {
        "Records": [
            {
                "messageId": message_id,
                "receiptHandle": "handle",
                "body": body,
                "attributes": {
                    "ApproximateReceiveCount": str(receive_count),
                    "SentTimestamp": "1791910499411",
                },
                "messageAttributes": {},
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:x-report-requests",
                "awsRegion": "us-east-1",
            }
        ]
    }


SQS_EVENT = sqs_event('{"week": "2026-W39", "source": "manual"}')


@pytest.mark.parametrize(
    ("event", "trigger"),
    [
        (SQS_EVENT, "sqs"),
        ({"source": "schedule"}, "schedule"),
        ({"week": None, "source": "schedule"}, "schedule"),
        ({"week": "2026-W40"}, "manual"),
        ({}, "manual"),
        ({"source": "something-else"}, "manual"),
        ({"Records": [{"eventSource": "aws:s3"}]}, "manual"),
        ({"Records": []}, "manual"),
    ],
)
def test_detect_trigger(event, trigger):
    assert detect_trigger(event) == trigger


def test_payload_of_an_sqs_event_is_the_message_body():
    assert payload_of(SQS_EVENT) == {"week": "2026-W39", "source": "manual"}


def test_the_schedule_message_names_no_week():
    payload = payload_of(sqs_event('{"week": null, "source": "schedule"}'))
    assert payload == {"week": None, "source": "schedule"}
    assert resolve_week(payload, NOW) == "2026-W41"


def test_delivery_of_an_sqs_event_counts_the_attempts():
    assert delivery_of(sqs_event("{}", receive_count=3, message_id="abc")) == {
        "messageId": "abc",
        "receiveCount": 3,
    }


def test_delivery_of_a_direct_invocation_is_empty():
    assert delivery_of({"source": "schedule"}) == {}


def test_payload_of_a_direct_invocation_is_the_event():
    assert payload_of({"week": "2026-W40", "source": "schedule"}) == {
        "week": "2026-W40",
        "source": "schedule",
    }


@pytest.mark.parametrize(
    ("payload", "week"),
    [
        ({"week": "2026-W39"}, "2026-W39"),
        ({"week": None, "source": "schedule"}, "2026-W41"),
        ({"source": "schedule"}, "2026-W41"),
        ({}, "2026-W41"),
    ],
)
def test_resolve_week_defaults_to_the_previous_iso_week(payload, week):
    assert resolve_week(payload, NOW) == week


def test_handler_rejects_a_bad_week_before_building_anything(monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "unused")
    with pytest.raises(ValueError):
        handler({"week": "last week"}, None)


def test_fail_week_raises_after_logging_the_attempt(monkeypatch, caplog):
    monkeypatch.setenv("FAIL_WEEK", "2026-W01")
    monkeypatch.setenv("REPORTS_BUCKET", "unused")
    event = sqs_event('{"week": "2026-W01", "source": "manual"}', receive_count=2)

    with caplog.at_level(logging.INFO, logger="meetings.reports"):
        with pytest.raises(RuntimeError, match="FAIL_WEEK test failure for 2026-W01"):
            handler(event, None)

    (record,) = [r for r in caplog.records if r.getMessage() == "report-builder triggered"]
    assert (record.trigger, record.week, record.source) == ("sqs", "2026-W01", "manual")
    assert (record.messageId, record.receiveCount) == ("m-1", 2)


def test_fail_week_leaves_other_weeks_alone(monkeypatch):
    monkeypatch.setenv("FAIL_WEEK", "2026-W01")
    monkeypatch.setenv("REPORTS_BUCKET", "unused")
    # Gets past the FAIL_WEEK check and stops at the week validation: no database, no S3.
    with pytest.raises(ValueError):
        handler(sqs_event('{"week": "not-a-week", "source": "manual"}'), None)
