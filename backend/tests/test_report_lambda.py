"""The report builder's event handling. No AWS: the S3 call is never reached."""

from datetime import datetime

import pytest

from app.config import settings
from app.reports.lambda_handler import detect_trigger, handler, payload_of, resolve_week

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=settings.tz)  # a Tuesday in 2026-W42

SQS_EVENT = {
    "Records": [
        {
            "messageId": "1",
            "eventSource": "aws:sqs",
            "body": '{"week": "2026-W39", "source": "make"}',
        }
    ]
}


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
