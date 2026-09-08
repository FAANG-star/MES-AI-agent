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
    }


@router.get("/machines", summary="Factory status strip")
async def machines(request: Request) -> ToolResult:
    """What the dashboard header shows. Backed by the same tool the agent uses."""
    ctx = _context(request)
    return await registry.invoke("get_machine_status", {}, ctx)


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
