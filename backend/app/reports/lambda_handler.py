"""AWS Lambda entry point of the report builder (the backend image, another handler).

Started by the schedule ({"source": "schedule"}), by hand ({"week": "2026-W40"},
or {} for last week), and from Step 4 by an SQS message. It builds the week's
CSV and saves it under reports/ in REPORTS_BUCKET; a failure raises, so the
caller (Lambda's retries, later SQS) sees it.
"""

import asyncio
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


def detect_trigger(event: dict[str, Any]) -> str:
    """Who started this invocation: "sqs", "schedule" or "manual"."""
    records = event.get("Records")
    if records and records[0].get("eventSource") == "aws:sqs":
        return "sqs"
    if event.get("source") == "schedule":
        return "schedule"
    return "manual"


def payload_of(event: dict[str, Any]) -> dict[str, Any]:
    """The command inside the event. For now the event itself; SQS arrives in Step 4."""
    return event


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
    week = resolve_week(payload_of(event), datetime.now(settings.tz))
    log.info("report-builder triggered", extra={"trigger": trigger, "week": week})

    key = report_key(week)  # ValueError for anything that is not an ISO week
    _s3().put_object(
        Bucket=os.environ["REPORTS_BUCKET"],
        Key=key,
        Body=build_weekly_report(week),
        ContentType="text/csv",
    )
    log.info("report saved", extra={"trigger": trigger, "week": week, "key": key})
    return {"week": week, "key": key}
