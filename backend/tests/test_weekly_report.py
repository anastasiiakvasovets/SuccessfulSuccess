"""The weekly report: week parsing, week boundaries and the CSV built from real rows."""

from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.models import Meeting, Participant, User
from app.reports import (
    build_weekly_report,
    parse_week,
    previous_iso_week,
    report_key,
    week_window,
)

KYIV = settings.tz


def _at(day: int, month: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=KYIV)


# --- weeks ------------------------------------------------------------------


@pytest.mark.parametrize("week", ["2026-W40", "2026-W01", "2020-W53"])
def test_parse_week_accepts_iso_weeks(week):
    year, number = parse_week(week)
    assert f"{year}-W{number:02d}" == week


@pytest.mark.parametrize(
    "week",
    ["2026-40", "2026-W4", "2026-w40", "2026-W00", "2026-W54", "2025-W53", " 2026-W40", "", None],
)
def test_parse_week_rejects_anything_else(week):
    with pytest.raises(ValueError):
        parse_week(week)


def test_report_key_is_one_file_per_week():
    assert report_key("2026-W40") == "reports/2026-W40.csv"
    with pytest.raises(ValueError):
        report_key("last week")


def test_week_window_is_monday_to_monday_in_kyiv():
    start, end = week_window("2026-W41")
    assert start == _at(5, 10, 0)
    assert end == _at(12, 10, 0)
    assert start.isoformat() == "2026-10-05T00:00:00+03:00"


def test_week_window_spans_the_dst_change():
    # Kyiv leaves summer time on Sunday 25 October 2026: that week is an hour longer.
    start, end = week_window("2026-W43")
    assert start.isoformat() == "2026-10-19T00:00:00+03:00"
    assert end.isoformat() == "2026-10-26T00:00:00+02:00"
    # Same-tzinfo subtraction is wall-clock time in Python; compare real instants.
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(days=7, hours=1)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 1, 5, 8, 0, tzinfo=KYIV), "2026-W01"),  # Monday of 2026-W02
        (datetime(2026, 1, 1, 12, 0, tzinfo=KYIV), "2025-W52"),  # inside 2026-W01
        (datetime(2021, 1, 4, 7, 0, tzinfo=KYIV), "2020-W53"),  # a 53-week year
        # Sunday 22:30 UTC is already Monday 01:30 in Kyiv: the week before is W41.
        (datetime(2026, 10, 11, 22, 30, tzinfo=UTC), "2026-W41"),
        (datetime(2026, 10, 12, 7, 0), "2026-W41"),  # naive means Kyiv time
    ],
)
def test_previous_iso_week(now, expected):
    assert previous_iso_week(now) == expected


# --- the report -------------------------------------------------------------


def _meeting(title, owner, start, minutes, participants=0):
    return Meeting(
        owner_id=owner,
        name=title,
        starts_at=start,
        ends_at=start + timedelta(minutes=minutes),
        participants=[Participant(name=f"P{i}", position=i) for i in range(participants)],
    )


@pytest.fixture
async def two_weeks(session):
    session.add_all(
        [
            User(id="user-a", email="a@example.com", name="Alice"),
            User(id="user-b", name="Bob"),
            User(id="user-c"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            # 2026-W41: Monday 5 October to Monday 12 October (Kyiv).
            # 00:30 Kyiv is still Sunday in UTC; it belongs to W41 all the same.
            _meeting("Long", "user-a", _at(5, 10, 0, 30), 180, participants=3),
            _meeting("Mid", "user-b", _at(6, 10, 9), 120, participants=2),
            _meeting("Short", "user-c", _at(7, 10, 12), 30),
            _meeting("Orphan", None, _at(8, 10, 10), 90, participants=1),
            _meeting("Tie A", "user-b", _at(9, 10, 14), 60, participants=1),
            _meeting("Tie B", "user-a", _at(9, 10, 9), 60),
            # Starts in W41 and ends in W42: counted in W41, where it starts.
            _meeting("Late Sunday", "user-a", _at(11, 10, 23, 30), 45),
            # 2026-W42: not in the report.
            _meeting("Next week", "user-a", _at(12, 10, 0), 600),
            # 2026-W40: the previous week.
            _meeting("Prev 1", "user-a", _at(30, 9, 10), 120),
            _meeting("Prev 2", "user-b", _at(4, 10, 23), 60),
        ]
    )
    await session.commit()


EXPECTED_W41 = """\
section,summary
week,meetings,hours,previous_week,previous_meetings,previous_hours,change_meetings,\
change_meetings_pct,change_hours,change_hours_pct
2026-W41,7,9.75,2026-W40,2,3.00,+5,+250.0,+6.75,+225.0

section,top_meetings
rank,title,start,duration_hours,participants
1,Long,2026-10-05T00:30:00+03:00,3.00,3
2,Mid,2026-10-06T09:00:00+03:00,2.00,2
3,Orphan,2026-10-08T10:00:00+03:00,1.50,1
4,Tie B,2026-10-09T09:00:00+03:00,1.00,0
5,Tie A,2026-10-09T14:00:00+03:00,1.00,1

section,per_organiser
organiser,meetings,hours
a@example.com,3,4.75
Bob,2,3.00
(no owner),1,1.50
user-c,1,0.50
"""


async def test_report_counts_hours_top_five_and_organisers(two_weeks):
    assert build_weekly_report("2026-W41").decode() == EXPECTED_W41


async def test_report_is_byte_identical_on_every_run(two_weeks):
    assert build_weekly_report("2026-W41") == build_weekly_report("2026-W41")


async def test_report_without_a_previous_week(two_weeks):
    report = build_weekly_report("2026-W40").decode()
    assert "2026-W40,2,3.00,2026-W39,0,0.00,+2,n/a,+3.00,n/a" in report


async def test_report_for_an_empty_week(two_weeks):
    lines = build_weekly_report("2026-W30").decode().splitlines()
    assert lines[2] == "2026-W30,0,0.00,2026-W29,0,0.00,+0,0.0,+0.00,0.0"
    # Each section keeps its header even with no rows under it.
    assert lines[4:] == [
        "section,top_meetings",
        "rank,title,start,duration_hours,participants",
        "",
        "section,per_organiser",
        "organiser,meetings,hours",
    ]


def test_report_rejects_a_bad_week_before_touching_the_database():
    with pytest.raises(ValueError):
        build_weekly_report("2026-W99")
