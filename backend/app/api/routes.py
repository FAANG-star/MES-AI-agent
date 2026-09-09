"""HTTP surface for the MES tool layer.

Two audiences:

  * the Day-8 dashboard, which needs the factory status strip (`/api/machines`);
  * the Day-4 agent and anyone auditing it, which needs to list the tools
    (`/api/tools`) and run one (`/api/tools/{name}`).

Exposing the tools over HTTP as well as in-process is deliberate: during a demo
you can show the factory manager the exact tool call and the exact JSON that
produced a number, which is the whole point of a controlled tool layer.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.schemas import Intent, Understanding
from app.agent.understanding import UnderstandingPipeline
from app.repositories.mes_repository import MesRepository
from app.schemas.envelope import ToolResult
from app.timewindow import WINDOW_LABELS, FactoryClock, WindowError
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
    clock = getattr(request.app.state, "clock", None) or FactoryClock(settings.factory_timezone)
    return ToolContext(repo=MesRepository(), clock=clock)


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
    try:
        rows = await ctx.repo.machine_ids()
        db_user = request.app.state.db_user
        machine_count = len(rows)
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
        },
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
    """Day 4: guard, rewrite, typed intent, grounded entities, and an ordered plan.

    Nothing is executed — no tool runs and no factory answer is produced here.
    Day 5 executes the plan this returns.
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
