"""The audit trail: one row per question in `agent_run_log`.

This is the evidence behind three acceptance criteria — that the agent called
tools (2), that the answer names the data it used (5), and that an out-of-domain
request touched nothing (7). In a demo it is also the backup slide: if a live run
misbehaves, the trace shows exactly what happened.

Writing is best-effort. A failure to record a run must never fail the run itself,
so the error is logged and the answer still reaches the user.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.schemas import AgentRun, StepStatus
from app.db import get_app_pool

log = logging.getLogger(__name__)


def _tool_calls_payload(run: AgentRun) -> list[dict[str, Any]]:
    """What ran, with what, and what came back — trimmed to what a reviewer reads."""
    return [
        {
            "step": s.step,
            "tool": s.tool,
            "kind": s.kind,
            "title": s.title,
            "status": s.status.value,
            "arguments": s.arguments,
            "resolved_bindings": s.resolved_bindings,
            "summary": s.summary,
            "sources": [src.model_dump() for src in s.sources],
            "missing_fields": [m.model_dump() for m in s.missing_fields],
            "not_found": s.not_found,
            "warnings": s.warnings,
            "elapsed_ms": s.elapsed_ms,
            "note": s.note,
        }
        for s in run.steps
    ]


async def record_run(run: AgentRun) -> bool:
    """Persist one run. Returns whether it was written."""
    pool = get_app_pool()
    if pool is None:
        log.debug("No application database pool; run %s not recorded.", run.run_id)
        return False

    understanding = run.understanding
    entities = understanding.entities.model_dump(mode="json") if understanding is not None else {}
    plan = (
        [p.model_dump(mode="json") for p in understanding.plan] if understanding is not None else []
    )

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_run_log (
                    run_id, question, rewritten, intent, entities, plan,
                    tool_calls, final_answer, status, grounded, latency_ms
                ) VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10, $11)
                ON CONFLICT (run_id) DO NOTHING
                """,
                run.run_id,
                run.question,
                run.rewritten_question,
                run.intent.value,
                json.dumps(entities),
                json.dumps(plan),
                json.dumps(_tool_calls_payload(run)),
                run.answer,
                run.status.value,
                run.validation.grounded,
                run.elapsed_ms,
            )
        return True
    except Exception as exc:  # pragma: no cover - the answer must survive a log failure
        log.warning("Could not record run %s: %s", run.run_id, exc)
        return False


async def read_trace(run_id: str) -> dict[str, Any] | None:
    pool = get_app_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT run_id::text, asked_at, question, rewritten, intent, entities, plan,
                   tool_calls, final_answer, status, grounded, latency_ms
              FROM agent_run_log WHERE run_id = $1::uuid
            """,
            run_id,
        )
    if row is None:
        return None
    trace = dict(row)
    for key in ("entities", "plan", "tool_calls"):
        if isinstance(trace.get(key), str):
            trace[key] = json.loads(trace[key])
    trace["asked_at"] = trace["asked_at"].isoformat()
    trace["tool_call_count"] = sum(
        1
        for call in trace.get("tool_calls") or []
        if call.get("status") == StepStatus.OK.value and call.get("kind", "tool") == "tool"
    )
    return trace


async def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    pool = get_app_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT run_id::text, asked_at, question, intent, status, latency_ms
              FROM agent_run_log ORDER BY asked_at DESC LIMIT $1
            """,
            limit,
        )
    return [{**dict(r), "asked_at": r["asked_at"].isoformat()} for r in rows]
