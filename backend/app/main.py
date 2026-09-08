"""FastAPI application for the Smart CNC Factory MES Copilot.

Day 3 serves the controlled MES tool layer. The agent graph (Days 4–7) will sit
on top of these same tools and add /api/ask; nothing below this line will need to
change for it, because the tools are the contract.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.db import close_pool, init_pool
from app.timewindow import FactoryClock
from app.tools.registry import registry

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    app.state.settings = settings
    app.state.clock = FactoryClock(settings.factory_timezone)

    pool = await init_pool(settings)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_user AS usr, current_setting('default_transaction_read_only') AS ro"
        )
    app.state.db_user = row["usr"]
    app.state.db_read_only = row["ro"] == "on"

    log.info(
        "MES Copilot ready — %s tools (%s implemented), factory time %s, db user %s (read_only=%s)",
        len(registry.names()),
        len(registry.implemented_names()),
        app.state.clock.today(),
        app.state.db_user,
        app.state.db_read_only,
    )
    try:
        yield
    finally:
        await close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Smart CNC Factory MES Copilot",
        description=(
            "Controlled MES tool layer. The language model never queries the database; "
            "it may only call the tools listed at /api/tools."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
