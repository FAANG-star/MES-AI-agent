"""FastAPI application for the Smart CNC Factory MES Copilot.

Day 3 serves the controlled MES tool layer. The agent graph (Days 4–7) will sit
on top of these same tools and add /api/ask; nothing below this line will need to
change for it, because the tools are the contract.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.extractor import warm_up
from app.api.routes import router
from app.config import get_settings
from app.db import close_pool, init_pool
from app.llm import build_llm_client
from app.llm.base import LLMError
from app.llm.openai_compatible import OpenAICompatibleLLMClient
from app.timewindow import FactoryClock
from app.tools.registry import registry

log = logging.getLogger(__name__)


async def _warm_up_in_background(settings) -> None:
    """Load the model and compile its grammar before anyone asks a question.

    A local model loads into memory on its first call, and the server compiles a
    grammar for the JSON schema the first time it sees one — together, minutes on
    CPU for a 7B model. That is far longer than a request should wait, so warming
    gets its own client with a much longer budget and runs in the background.
    """
    warm_settings = settings.model_copy(update={"llm_timeout_s": settings.llm_warmup_timeout_s})
    client, _ = build_llm_client(warm_settings)
    if client is None:
        return
    started = time.perf_counter()
    try:
        await warm_up(client)
        log.info(
            "Model %s ready after %.0fs of warm-up",
            settings.llm_model,
            time.perf_counter() - started,
        )
    except LLMError as exc:
        log.warning("Warm-up did not complete (%s); the first question may be slow.", exc)
    except asyncio.CancelledError:
        raise
    finally:
        await client.aclose()


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

    # One LLM client for the process. `None` is a supported state: the agent
    # falls back to deterministic understanding and says so in every response.
    llm, reason = build_llm_client(settings)

    # A local model that is configured but not running would otherwise cost
    # every request a connection timeout before falling back. Probe once at
    # startup and treat an unreachable endpoint as "no provider".
    if llm is not None and isinstance(llm, OpenAICompatibleLLMClient):
        try:
            probe = await llm.probe()
            if not probe["model_present"]:
                log.warning(
                    "Model %s is not served by %s (available: %s). Requests may fail.",
                    settings.llm_model,
                    settings.llm_base_url,
                    probe["models"],
                )
        except LLMError as exc:
            await llm.aclose()
            llm = None
            reason = (
                f"Local model at {settings.llm_base_url} is not reachable ({exc}); "
                "using deterministic understanding. Start the model server and restart, "
                "or run `make llm-check`."
            )

    app.state.llm = llm
    app.state.llm_provider = llm.name if llm else "none"
    app.state.llm_reason = reason
    (log.info if llm else log.warning)("LLM: %s", reason)

    # Warm the model without blocking startup. The API is usable immediately —
    # on rules until the model is ready, then on the model.
    app.state.warmup_task = None
    if llm is not None and settings.llm_warmup:
        app.state.warmup_task = asyncio.create_task(_warm_up_in_background(settings))

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
        task = getattr(app.state, "warmup_task", None)
        if task is not None and not task.done():
            task.cancel()
        if app.state.llm is not None:
            await app.state.llm.aclose()
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
