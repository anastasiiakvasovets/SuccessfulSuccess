"""AWS Lambda entry point of the report builder (the backend image, another handler).

Started by an SQS message from the schedule ({"week": null, "source": "schedule"})
or `make report-now` ({"week": "2026-W40", "source": "manual"}), and still by a
direct invocation with the same payload. It builds the week's CSV and saves it
under reports/ in REPORTS_BUCKET. A failure raises: the message becomes visible
again, and after three attempts SQS moves it to the dead-letter queue.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from functools import cache
from typing import Any

import boto3

from app.config import settings
from app.db import engine
from app.reports.seed_weeks import seed_weeks
from app.reports.weekly import build_weekly_report, previous_iso_week, report_key

log = logging.getLogger("meetings.reports")
log.setLevel(settings.log_level.upper())


def sqs_record(event: dict[str, Any]) -> dict[str, Any] | None:
    """The SQS message of this invocation (the mapping's batch size is 1), or None."""
    records = event.get("Records")
    if records and records[0].get("eventSource") == "aws:sqs":
        return records[0]
    return None


def detect_trigger(event: dict[str, Any]) -> str:
    """Who started this invocation: "sqs", "schedule" or "manual"."""
    if sqs_record(event) is not None:
        return "sqs"
    if event.get("source") == "schedule":
        return "schedule"
    return "manual"


def payload_of(event: dict[str, Any]) -> dict[str, Any]:
    """The command: an SQS message's JSON body, or a direct invocation's event itself."""
    record = sqs_record(event)
    return json.loads(record["body"]) if record is not None else event


def delivery_of(event: dict[str, Any]) -> dict[str, Any]:
    """messageId and receive count of an SQS delivery, for the log; {} otherwise.

    The count goes 1, 2, 3 as a failing message is retried, then it moves to the DLQ.
    """
    record = sqs_record(event)
    if record is None:
        return {}
    return {
        "messageId": record.get("messageId"),
        "receiveCount": int(record.get("attributes", {}).get("ApproximateReceiveCount", 0)),
    }


def resolve_week(payload: dict[str, Any], now: datetime) -> str:
    """The week the payload asks for, or the one before `now` when it names none.

    Not validated here, so a bad week is still logged before report_key rejects it.
    """
    return payload.get("week") or previous_iso_week(now)


@cache
def _s3():
    return boto3.client("s3")


def _seed_weeks() -> dict[str, int]:
    """Load the demo meetings into this database (RDS has no public access)."""

    async def run() -> int:
        try:
            return await seed_weeks()
        finally:
            # The pooled connection belongs to this event loop, which closes now.
            await engine.dispose()

    return {"seeded": asyncio.run(run())}


def handler(event, context):
    if event.get("action") == "seed-weeks":
        log.info("report-builder seeding demo meetings", extra={"trigger": "manual"})
        return _seed_weeks()

    trigger = detect_trigger(event)
    payload = payload_of(event)
    week = resolve_week(payload, datetime.now(settings.tz))
    log.info(
        "report-builder triggered",
        extra={"trigger": trigger, "week": week, "source": payload.get("source")}
        | delivery_of(event),
    )

    # Deploy with FAIL_WEEK=<week> to watch a failing message reach the DLQ.
    if week == os.environ.get("FAIL_WEEK"):
        raise RuntimeError(f"FAIL_WEEK test failure for {week}")

    key = report_key(week)  # ValueError for anything that is not an ISO week
    _s3().put_object(
        Bucket=os.environ["REPORTS_BUCKET"],
        Key=key,
        Body=build_weekly_report(week),
        ContentType="text/csv",
    )
    log.info("report saved", extra={"trigger": trigger, "week": week, "key": key})
    return {"week": week, "key": key}
