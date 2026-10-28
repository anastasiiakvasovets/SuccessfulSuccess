"""The saved agendas next to what the parser suggested (Lab 6). Read-only.

The difference between the two is the parser's quality signal. RDS has no
public access, so `make aws-agendas` asks the API function to run this
({"action": "show-agendas"}); `make agendas-local` reads the compose database.

    python -m app.ai.suggestions [limit]
"""

import asyncio
import json
import sys
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Meeting


async def latest_agendas(limit: int = 5) -> list[dict[str, Any]]:
    """The `limit` most recently saved agendas, newest first, across all users."""
    # Its own connection, not the app's pool: the API function's pool belongs to
    # another event loop. READ ONLY makes Postgres refuse any write.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = await connection.execute(
                select(
                    Meeting.name,
                    Meeting.starts_at,
                    Meeting.updated_at,
                    Meeting.agenda,
                    Meeting.ai_suggestion,
                    Meeting.ai_model,
                    Meeting.ai_prompt_version,
                )
                .where(Meeting.agenda.is_not(None))
                .order_by(Meeting.updated_at.desc())
                .limit(max(1, min(limit, 50)))
            )
            return [
                {
                    **row,
                    "starts_at": row["starts_at"].astimezone(settings.tz).isoformat(),
                    "updated_at": row["updated_at"].astimezone(settings.tz).isoformat(),
                }
                for row in rows.mappings()
            ]
    finally:
        await engine.dispose()


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(json.dumps(asyncio.run(latest_agendas(limit)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
