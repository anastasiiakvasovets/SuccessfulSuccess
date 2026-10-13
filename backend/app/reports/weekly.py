"""The weekly meetings report: one ISO week of meetings, across every user, as a CSV.

No AWS in here. The caller decides which week; `previous_iso_week` is a helper
for callers that want "last week", and is never used by the report itself.
`python -m app.reports [2026-W41]` prints a report (see __main__.py).
"""

import asyncio
import csv
import io
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Meeting, Participant, User

WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")
TOP_MEETINGS = 5
NO_OWNER = "(no owner)"


def parse_week(week: str) -> tuple[int, int]:
    """Return (ISO year, ISO week) for "2026-W40"; ValueError for anything else."""
    match = WEEK_PATTERN.match(week) if isinstance(week, str) else None
    if match is None:
        raise ValueError(f"week must look like 2026-W40, got {week!r}")
    year, number = int(match[1]), int(match[2])
    try:
        # Rejects W00, and W53 in years that only have 52 ISO weeks.
        date.fromisocalendar(year, number, 1)
    except ValueError:
        raise ValueError(f"{week!r} is not an ISO week") from None
    return year, number


def report_key(week: str) -> str:
    """The S3 key of a week's report: the same week always gives the same key."""
    year, number = parse_week(week)
    return f"reports/{year:04d}-W{number:02d}.csv"


def iso_week_of(day: date) -> str:
    year, number, _ = day.isocalendar()
    return f"{year:04d}-W{number:02d}"


def previous_iso_week(now: datetime) -> str:
    """The ISO week before the one `now` falls in, in the application timezone.

    A naive `now` is taken to be application-timezone wall-clock time.
    """
    local = now.astimezone(settings.tz) if now.tzinfo else now.replace(tzinfo=settings.tz)
    return iso_week_of(local.date() - timedelta(days=7))


def week_window(week: str) -> tuple[datetime, datetime]:
    """[Monday 00:00, next Monday 00:00) of an ISO week in the application timezone."""
    monday = date.fromisocalendar(*parse_week(week), 1)
    tz = settings.tz
    # combine() per day keeps both ends at local midnight across a DST change.
    return (
        datetime.combine(monday, time.min, tzinfo=tz),
        datetime.combine(monday + timedelta(days=7), time.min, tzinfo=tz),
    )


def shift_week(week: str, weeks: int) -> str:
    monday = date.fromisocalendar(*parse_week(week), 1)
    return iso_week_of(monday + timedelta(weeks=weeks))


@dataclass(frozen=True)
class MeetingRow:
    id: uuid.UUID
    title: str
    starts_at: datetime
    hours: float
    participants: int
    owner_id: str | None
    owner_label: str


async def _fetch_week(connection, week: str) -> list[MeetingRow]:
    """Every meeting that starts in the week, whoever owns it."""
    start, end = week_window(week)
    participant_counts = (
        select(Participant.meeting_id, func.count().label("n"))
        .group_by(Participant.meeting_id)
        .subquery()
    )
    statement = (
        select(
            Meeting.id,
            Meeting.name,
            Meeting.starts_at,
            Meeting.ends_at,
            Meeting.owner_id,
            User.email,
            User.name.label("owner_name"),
            func.coalesce(participant_counts.c.n, 0).label("participants"),
        )
        .outerjoin(User, User.id == Meeting.owner_id)
        .outerjoin(participant_counts, participant_counts.c.meeting_id == Meeting.id)
        .where(Meeting.starts_at >= start, Meeting.starts_at < end)
    )
    rows = (await connection.execute(statement)).all()
    return [
        MeetingRow(
            id=row.id,
            title=row.name,
            starts_at=row.starts_at,
            hours=(row.ends_at - row.starts_at).total_seconds() / 3600,
            participants=int(row.participants),
            owner_id=row.owner_id,
            owner_label=(
                (row.email or row.owner_name or row.owner_id) if row.owner_id else NO_OWNER
            ),
        )
        for row in rows
    ]


async def fetch_report_data(week: str) -> tuple[list[MeetingRow], list[MeetingRow]]:
    """(this week's meetings, the previous week's), on an engine of their own.

    NullPool and dispose(): nothing outlives the call, so it is safe to run on
    a fresh event loop every time (a Lambda invocation, a script, a thread).
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            current = await _fetch_week(connection, week)
            previous = await _fetch_week(connection, shift_week(week, -1))
    finally:
        await engine.dispose()
    return current, previous


def _hours(value: float) -> str:
    return f"{value:.2f}"


def _change_pct(current: float, previous: float) -> str:
    if previous == 0:
        return "0.0" if current == 0 else "n/a"
    return f"{(current - previous) / previous * 100:+.1f}"


def render_csv(week: str, current: list[MeetingRow], previous: list[MeetingRow]) -> bytes:
    """Three sections, each a header row plus data, separated by a blank line.

    Every list is sorted on a full key, so the same data always gives the same bytes.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")

    count, hours = len(current), sum(m.hours for m in current)
    prev_count, prev_hours = len(previous), sum(m.hours for m in previous)
    writer.writerow(["section", "summary"])
    writer.writerow(
        [
            "week",
            "meetings",
            "hours",
            "previous_week",
            "previous_meetings",
            "previous_hours",
            "change_meetings",
            "change_meetings_pct",
            "change_hours",
            "change_hours_pct",
        ]
    )
    writer.writerow(
        [
            week,
            count,
            _hours(hours),
            shift_week(week, -1),
            prev_count,
            _hours(prev_hours),
            f"{count - prev_count:+d}",
            _change_pct(count, prev_count),
            f"{hours - prev_hours:+.2f}",
            _change_pct(round(hours, 2), round(prev_hours, 2)),
        ]
    )

    writer.writerow([])
    writer.writerow(["section", "top_meetings"])
    writer.writerow(["rank", "title", "start", "duration_hours", "participants"])
    longest = sorted(current, key=lambda m: (-m.hours, m.starts_at, m.title, m.id))
    for rank, meeting in enumerate(longest[:TOP_MEETINGS], start=1):
        writer.writerow(
            [
                rank,
                meeting.title,
                meeting.starts_at.astimezone(settings.tz).isoformat(),
                _hours(meeting.hours),
                meeting.participants,
            ]
        )

    writer.writerow([])
    writer.writerow(["section", "per_organiser"])
    writer.writerow(["organiser", "meetings", "hours"])
    totals: dict[str | None, tuple[str, int, float]] = {}
    for meeting in current:
        label, n, h = totals.get(meeting.owner_id, (meeting.owner_label, 0, 0.0))
        totals[meeting.owner_id] = (label, n + 1, h + meeting.hours)
    ranked = sorted(
        totals.items(),
        key=lambda item: (-round(item[1][2], 2), -item[1][1], item[1][0], item[0] or ""),
    )
    for _, (label, n, h) in ranked:
        writer.writerow([label, n, _hours(h)])

    return out.getvalue().encode("utf-8")


async def build_weekly_report_async(week: str) -> bytes:
    parse_week(week)
    current, previous = await fetch_report_data(week)
    return render_csv(week, current, previous)


def build_weekly_report(week: str) -> bytes:
    """Query the meetings of one ISO week (e.g. "2026-W40") and return the CSV."""
    parse_week(week)  # fail before touching the database
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(build_weekly_report_async(week))
    # Called from async code: asyncio.run cannot nest, so use a thread's own loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, build_weekly_report_async(week)).result()
