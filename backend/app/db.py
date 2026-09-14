"""Database access for the MES tool layer.

One asyncpg pool, connected as `mes_ro` (ADR-6). That role holds SELECT grants
only and carries `default_transaction_read_only`, so a bug in a tool — or a
prompt injection that somehow reached this layer — still cannot change factory
data. The application's read-write URL exists for the audit trail and is
deliberately not used here.

Every query in the repository layer is a fixed, parameterised statement. No SQL
is ever assembled from model output (ADR-2).
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_app_pool: asyncpg.Pool | None = None


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    settings = settings or get_settings()
    pool = await asyncpg.create_pool(
        dsn=settings.database_url_ro,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        command_timeout=settings.db_command_timeout_s,
        server_settings={"application_name": "mes-copilot-tools"},
    )
    async with pool.acquire() as conn:
        user, read_only = await conn.fetchrow(
            "SELECT current_user, current_setting('default_transaction_read_only')"
        )
        log.info("MES tool layer connected as %s (read_only=%s)", user, read_only)
        if read_only != "on":
            log.warning(
                "Tool connection is NOT read-only. Re-apply db/schema.sql to fix the mes_ro role."
            )
    return pool


async def init_pool(settings: Settings | None = None) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_pool(settings)
    return _pool


async def init_app_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """The application's own read-write connection.

    Separate from the tool pool on purpose (ADR-6). Tools connect as `mes_ro` and
    cannot write anything; the audit trail is the application's record of what it
    did, so it is written here. Keeping the two apart means the read-only
    guarantee on the tool path has no exception carved into it.
    """
    global _app_pool
    settings = settings or get_settings()
    if _app_pool is None:
        _app_pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=max(2, settings.db_pool_max_size // 2),
            command_timeout=settings.db_command_timeout_s,
            server_settings={"application_name": "mes-copilot-app"},
        )
    return _app_pool


def get_app_pool() -> asyncpg.Pool | None:
    return _app_pool


async def close_pool() -> None:
    global _pool, _app_pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _app_pool is not None:
        await _app_pool.close()
        _app_pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialised. Call init_pool() first.")
    return _pool


async def fetch(sql: str, *args: Any, pool: asyncpg.Pool | None = None) -> list[asyncpg.Record]:
    async with (pool or get_pool()).acquire() as conn:
        return await conn.fetch(sql, *args)


async def fetchrow(sql: str, *args: Any, pool: asyncpg.Pool | None = None) -> asyncpg.Record | None:
    async with (pool or get_pool()).acquire() as conn:
        return await conn.fetchrow(sql, *args)
