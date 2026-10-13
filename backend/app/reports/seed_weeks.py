"""Insert demo meetings over the last two ISO weeks, for trying the weekly report.

Two demo users, ~15 meetings with participants. Runs once: if the demo users
already own meetings, it does nothing.

Usage: python -m app.reports.seed_weeks
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db import SessionFactory
from app.models import Meeting, Participant, User
from app.reports.weekly import parse_week, previous_iso_week, shift_week

logger = logging.getLogger("meetings.seed_weeks")

OLENA, TARAS = "seed-olena", "seed-taras"
USERS = [
    (OLENA, "olena@example.com", "Olena Demo"),
    (TARAS, "taras@example.com", "Taras Demo"),
]

# (weeks before last week, weekday 1-7, start, minutes, title, owner, participants)
DEMO = [
    (0, 1, time(9, 30), 30, "Weekly kickoff", OLENA, ["Olena", "Taras", "Iryna"]),
    (0, 1, time(14, 0), 90, "Roadmap review", OLENA, ["Olena", "Maksym"]),
    (0, 2, time(11, 0), 60, "Customer interview", TARAS, ["Taras", "Sofia"]),
    (0, 3, time(10, 0), 120, "Architecture workshop", TARAS, ["Taras", "Olena", "Andrii", "Iryna"]),
    (0, 3, time(16, 0), 45, "1:1 Olena / Maksym", OLENA, ["Olena", "Maksym"]),
    (0, 4, time(13, 0), 150, "Hiring panel", OLENA, ["Olena", "Sofia", "Andrii"]),
    (0, 5, time(15, 0), 60, "Sprint demo", TARAS, ["Taras", "Olena", "Iryna", "Sofia", "Maksym"]),
    (0, 5, time(17, 0), 30, "Retro", TARAS, ["Taras", "Olena"]),
    (1, 1, time(9, 30), 30, "Weekly kickoff", OLENA, ["Olena", "Taras"]),
    (1, 2, time(10, 0), 60, "Budget planning", OLENA, ["Olena", "Andrii"]),
    (1, 2, time(15, 0), 90, "Incident review", TARAS, ["Taras", "Iryna", "Sofia"]),
    (1, 3, time(12, 0), 45, "Design critique", TARAS, ["Taras", "Sofia"]),
    (1, 4, time(11, 0), 60, "Partner call", OLENA, ["Olena"]),
    (1, 4, time(14, 30), 120, "Quarterly planning", OLENA, ["Olena", "Taras", "Maksym", "Iryna"]),
    (1, 5, time(16, 0), 30, "Friday wrap-up", TARAS, ["Taras", "Olena", "Andrii"]),
]


async def seed_weeks(now: datetime | None = None) -> int:
    """Insert the demo meetings unless they are there already; return how many were added."""
    last_week = previous_iso_week(now or datetime.now(settings.tz))
    user_ids = [user_id for user_id, _, _ in USERS]

    async with SessionFactory() as session:
        existing = await session.scalar(
            select(func.count()).select_from(Meeting).where(Meeting.owner_id.in_(user_ids))
        )
        if existing:
            logger.info("Demo users already own %d meetings; nothing to do.", existing)
            return 0

        await session.execute(
            insert(User)
            .values(
                [
                    {"id": user_id, "email": email, "name": name, "email_verified": True}
                    for user_id, email, name in USERS
                ]
            )
            .on_conflict_do_nothing()
        )
        for weeks_back, weekday, start, minutes, title, owner_id, people in DEMO:
            week = shift_week(last_week, -weeks_back)
            day = date.fromisocalendar(*parse_week(week), weekday)
            starts_at = datetime.combine(day, start, tzinfo=settings.tz)
            session.add(
                Meeting(
                    owner_id=owner_id,
                    name=title,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=minutes),
                    participants=[
                        Participant(name=person, position=index)
                        for index, person in enumerate(people)
                    ],
                )
            )
        await session.commit()

    logger.info("Seeded %d meetings in %s and %s.", len(DEMO), shift_week(last_week, -1), last_week)
    return len(DEMO)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_weeks())
