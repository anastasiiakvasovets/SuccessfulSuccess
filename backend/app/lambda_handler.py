"""AWS Lambda entry point: the API behind the function URL, plus on-demand migrations
and a read-only look at the saved agendas."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alembic.config import Config
from mangum import Mangum

from alembic import command
from app.ai.suggestions import latest_agendas
from app.main import app

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# Mangum keeps one event loop for the life of the execution environment, so the
# pooled asyncpg connection survives from one invocation to the next. The app
# has no lifespan work to do.
api = Mangum(app, lifespan="off")


def migrate() -> None:
    """Apply migrations."""
    command.upgrade(Config(str(ALEMBIC_INI)), "head")


def handler(event, context):
    # `make aws-migrate` invokes the function directly with this payload.
    # Function URL events never carry an "action" key, so no request can.
    if event.get("action") == "migrate":
        # Alembic calls asyncio.run, which closes and unsets the thread's event
        # loop when it returns. A worker thread keeps Mangum's loop untouched.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(migrate).result()
        return {"status": "migrated"}
    # `make aws-agendas`: saved agendas next to the AI suggestion, read-only.
    if event.get("action") == "show-agendas":
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                lambda: asyncio.run(latest_agendas(int(event.get("limit", 5))))
            ).result()
    return api(event, context)
