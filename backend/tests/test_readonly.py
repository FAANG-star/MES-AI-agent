"""ADR-6: the tool layer physically cannot change factory data.

This is a security property, so it is asserted against the live connection the
tools actually use rather than trusted from documentation.
"""

from __future__ import annotations

import asyncpg
import pytest

from tests.conftest import requires_db

pytestmark = requires_db


async def test_tools_connect_as_the_read_only_role(pool):
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT current_user") == "mes_ro"
        assert (
            await conn.fetchval("SELECT current_setting('default_transaction_read_only')") == "on"
        )


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM machines",
        "UPDATE parts SET cycle_time_min = 1",
        "INSERT INTO inventory (material_id, material_name, unit) VALUES ('X', 'x', 'pcs')",
        "DROP TABLE production_history",
    ],
)
async def test_every_write_is_refused(pool, statement):
    async with pool.acquire() as conn:
        with pytest.raises(
            (asyncpg.InsufficientPrivilegeError, asyncpg.ReadOnlySQLTransactionError)
        ):
            await conn.execute(statement)


async def test_reads_still_work(pool):
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM machines") == 5
