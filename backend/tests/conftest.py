"""Test fixtures.

The tool tests run against the seeded database, because a tool's job is to read
the real MES correctly — mocking the rows would test nothing. They skip cleanly
when no database is reachable, so `pytest` still works on a laptop without Docker.
"""

from __future__ import annotations

import asyncio
import os

# The test suite must not depend on a language model being reachable, and must
# never pay a model warm-up. The LLM paths have their own tests, driven by stubs
# and a fake OpenAI-compatible server; everything else runs on the deterministic
# path. Set before app.config is imported, so the cached settings pick it up.
os.environ["LLM_PROVIDER"] = "none"
os.environ["LLM_WARMUP"] = "false"


import asyncpg
import pytest
import pytest_asyncio

from app.config import get_settings
from app.db import create_pool
from app.repositories.mes_repository import MesRepository
from app.timewindow import FactoryClock
from app.tools.registry import ToolContext


def _database_reachable() -> bool:
    async def probe() -> bool:
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(dsn=get_settings().database_url_ro), timeout=3
            )
        except Exception:
            return False
        await conn.close()
        return True

    try:
        return asyncio.run(probe())
    except Exception:
        return False


DB_AVAILABLE = _database_reachable()
requires_db = pytest.mark.skipif(not DB_AVAILABLE, reason="seeded MES database is not reachable")


@pytest_asyncio.fixture
async def pool():
    p = await create_pool()
    try:
        yield p
    finally:
        await p.close()


@pytest_asyncio.fixture
async def app_pool():
    """The application's read-write pool, used only for the audit trail (ADR-6)."""
    import app.db as db_module

    pool = await db_module.init_app_pool()
    try:
        yield pool
    finally:
        await pool.close()
        db_module._app_pool = None


@pytest_asyncio.fixture
async def repo(pool):
    return MesRepository(pool)


@pytest_asyncio.fixture
async def ctx(repo):
    return ToolContext(repo=repo, clock=FactoryClock(get_settings().factory_timezone))
