"""Print one week's report as CSV: python -m app.reports [2026-W41]

Without a week it prints the previous ISO week's, in the application timezone.
"""

import sys
from datetime import datetime

from app.config import settings
from app.reports.weekly import build_weekly_report, previous_iso_week

if len(sys.argv) > 2:
    sys.exit("Usage: python -m app.reports [2026-W41]")
week = sys.argv[1] if len(sys.argv) == 2 else previous_iso_week(datetime.now(settings.tz))
try:
    sys.stdout.buffer.write(build_weekly_report(week))
except ValueError as error:
    sys.exit(str(error))
