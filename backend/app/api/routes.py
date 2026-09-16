"""HTTP surface for the MES tool layer.

Two audiences:

  * the web interface, which needs the factory status strip (`/api/machines`);
  * the agent and anyone auditing it, which needs to list the tools
    (`/api/tools`) and run one (`/api/tools/{name}`).

Exposing the tools over HTTP as well as in-process is deliberate: during a demo
you can show the factory manager the exact tool call and the exact JSON that
produced a number, which is the whole point of a controlled tool layer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import dataset
from app.agent.pipeline import AgentPipeline
from app.agent.schemas import AgentRun, Intent, Understanding
from app.agent.tracing import read_trace, recent_runs
from app.agent.understanding import UnderstandingPipeline
from app.repositories.mes_repository import MesRepository
from app.schemas.envelope import ToolResult
from app.timewindow import WINDOW_LABELS, WindowError
from app.tools import registry  # importing the package registers all eight tools
from app.tools.registry import (
    ToolContext,
    ToolNotImplementedError,
    ToolParameterError,
    UnknownToolError,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _context(request: Request) -> ToolContext:
    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None) or settings.factory_clock()
    return ToolContext(repo=MesRepository(), clock=clock)


def _agent(request: Request) -> AgentPipeline:
    ctx = _context(request)
    return AgentPipeline(
        repo=ctx.repo,
        clock=ctx.clock,
        llm=request.app.state.llm,
        provider_name=request.app.state.llm_provider,
        explainer_temperature=request.app.state.settings.llm_explainer_temperature,
    )


def _pipeline(request: Request) -> UnderstandingPipeline:
    ctx = _context(request)
    return UnderstandingPipeline(
        repo=ctx.repo,
        clock=ctx.clock,
        llm=request.app.state.llm,
        provider_name=request.app.state.llm_provider,
    )


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1, max_length=1000, description="A factory question in plain English"
    )


@router.get("/health", summary="Liveness and factory clock")
async def health(request: Request) -> dict[str, Any]:
    ctx = _context(request)
    db_ok, db_error, db_user = True, None, None
    freshness = None
    try:
        rows = await ctx.repo.machine_ids()
        db_user = request.app.state.db_user
        machine_count = len(rows)
        freshness = dataset.assess(await ctx.repo.last_production_day(), ctx.clock.today())
    except Exception as exc:  # pragma: no cover — only on a broken database
        db_ok, db_error, machine_count = False, str(exc), 0
    return {
        "status": "ok" if db_ok else "degraded",
        "database": {
            "connected": db_ok,
            "user": db_user,
            "read_only": request.app.state.db_read_only,
            "machines": machine_count,
            "error": db_error,
        },
        "factory": {
            "timezone": ctx.clock.timezone,
            "today": ctx.clock.today().isoformat(),
            "now": ctx.clock.now().isoformat(),
            # True during a rehearsal (FACTORY_TODAY set). The interface says so,
            # because a pinned calendar left on would quietly answer about the
            # wrong day.
            "pinned": ctx.clock._fixed_today is not None,
        },
        # The seeded week is relative to "today" (see `app/dataset.py`). A
        # database seeded yesterday still answers consistently, so nothing
        # noticed until a demo scenario stopped holding.
        "dataset": freshness.as_json() if freshness else None,
        "tools": {
            "total": len(registry.names()),
            "implemented": len(registry.implemented_names()),
        },
        "agent": {
            "llm_provider": request.app.state.llm_provider,
            "llm_available": request.app.state.llm is not None,
            "understanding": "llm" if request.app.state.llm else "deterministic_rules",
        },
    }


@router.get("/machines", summary="Factory status strip")
async def machines(request: Request) -> ToolResult:
    """What the dashboard header shows. Backed by the same tool the agent uses."""
    ctx = _context(request)
    return await registry.invoke("get_machine_status", {}, ctx)


@router.post("/understand", summary="Understand a question and plan the MES calls")
async def understand(request: Request, body: AskRequest) -> Understanding:
    """Guard, rewrite, typed intent, grounded entities, and an ordered plan.

    Nothing is executed — no tool runs and no factory answer is produced here.
    `/api/ask` executes the plan this returns.
    """
    return await _pipeline(request).understand(body.question)


@router.get("/agent", summary="How the understanding layer is configured")
async def agent_info(request: Request) -> dict[str, Any]:
    return {
        "llm": {
            "provider": request.app.state.llm_provider,
            "model": request.app.state.settings.llm_model,
            "available": request.app.state.llm is not None,
            "status": request.app.state.llm_reason,
            "degraded": request.app.state.llm is None,
        },
        "intents": [i.value for i in Intent],
        "pipeline": ["domain_guard", "rewrite_and_intent", "entity_resolution", "tool_selection"],
        "note": (
            "With no language model available the agent falls back to deterministic rule-based "
            "understanding; every response reports which path produced it."
        ),
    }


@router.post("/ask", summary="Ask the factory a question")
async def ask(request: Request, body: AskRequest) -> AgentRun:
    """The complete workflow: understand, plan, execute, record.

    Returns the finished run. Use `/api/ask/stream` to watch it happen.
    """
    return await _agent(request).ask(body.question)


@router.post("/ask/stream", summary="Ask, streaming each analysis step as it completes")
async def ask_stream(request: Request, body: AskRequest) -> StreamingResponse:
    """Server-sent events: `accepted`, `understanding`, `tool_result`, `error`, `run`.

    The same execution path as `/api/ask`, forwarded as it happens, so the
    analysis panel fills in step by step instead of after everything finishes.
    """
    agent = _agent(request)

    async def events():
        try:
            async for event in agent.stream(body.question):
                yield f"event: {event.kind}\ndata: {json.dumps(event.payload)}\n\n"
        except Exception as exc:  # pragma: no cover - the stream must close cleanly
            log.exception("Streaming run failed")
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.get("/traces", summary="Recent runs")
async def list_traces(limit: int = 20) -> dict[str, Any]:
    return {"runs": await recent_runs(min(max(limit, 1), 100))}


@router.get("/traces/{run_id}", summary="The full audit trace of one question")
async def get_trace(run_id: str) -> dict[str, Any]:
    trace = await read_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}.")
    return trace


@router.get("/tools", summary="The controlled tool catalogue")
async def list_tools() -> dict[str, Any]:
    """Exactly the tools the model may call — nothing else is reachable."""
    return {
        "tools": registry.schemas(),
        "implemented": registry.implemented_names(),
        "time_windows": WINDOW_LABELS,
    }


@router.get("/tools/{tool_name}", summary="One tool's contract")
async def describe_tool(tool_name: str) -> dict[str, Any]:
    try:
        return registry.get(tool_name).json_schema()
    except UnknownToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tools/{tool_name}", summary="Invoke a MES tool")
async def invoke_tool(
    request: Request, tool_name: str, params: dict[str, Any] | None = Body(default=None)
) -> ToolResult:
    ctx = _context(request)
    try:
        return await registry.invoke(tool_name, params or {}, ctx)
    except UnknownToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ToolNotImplementedError as exc:
        raise HTTPException(
            status_code=501,
            detail={"error": str(exc), "tool": exc.name, "planned_for": exc.planned_for},
        ) from exc
    except ToolParameterError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "invalid_parameters", "errors": exc.errors}
        ) from exc
    except WindowError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "invalid_time_window", "message": str(exc)}
        ) from exc
