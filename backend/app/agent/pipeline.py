"""One question in, one structured run out — the whole workflow (FR-1 … FR-5).

    question
      → understand   guard, rewrite, typed intent, entities, plan   (Day 4)
      → execute      each step through the controlled tool layer    (Day 5)
      → record       one row in agent_run_log                       (Day 5)

`ask()` returns the finished run. `stream()` yields the same work as it happens,
so the UI can show each analysis step the moment it completes rather than after
everything finishes — which matters when understanding alone takes seconds on a
local model.

Both paths run the identical code and produce the identical `AgentRun`; the
stream is a view of the work, not a second implementation of it.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator

from app.agent.executor import PlanExecutor
from app.agent.schemas import AgentRun, RunStatus, UnderstandingStatus
from app.agent.tracing import record_run
from app.agent.understanding import UnderstandingPipeline
from app.llm.base import LLMClient
from app.repositories.mes_repository import MesRepository
from app.timewindow import FactoryClock
from app.tools.registry import ToolContext

log = logging.getLogger(__name__)


class AgentPipeline:
    def __init__(
        self,
        *,
        repo: MesRepository,
        clock: FactoryClock,
        llm: LLMClient | None = None,
        provider_name: str = "none",
    ) -> None:
        self._ctx = ToolContext(repo=repo, clock=clock)
        self._understanding = UnderstandingPipeline(
            repo=repo, clock=clock, llm=llm, provider_name=provider_name
        )
        self._executor = PlanExecutor(self._ctx)

    async def ask(self, question: str) -> AgentRun:
        run: AgentRun | None = None
        async for event in self.stream(question):
            if event.kind == "run":
                run = event.run
        assert run is not None  # stream() always ends with a run event
        return run

    async def stream(self, question: str) -> AsyncIterator[AgentEvent]:
        """Yield the workflow as it happens, ending with the complete run."""
        started = time.perf_counter()
        run_id = str(uuid.uuid4())

        yield AgentEvent("accepted", {"run_id": run_id, "question": question})

        understanding = await self._understanding.understand(question)
        yield AgentEvent(
            "understanding",
            {
                "run_id": run_id,
                "status": understanding.status.value,
                "intent": understanding.intent.value,
                "metric": understanding.metric.value,
                "rewritten_question": understanding.rewritten_question,
                "window": understanding.window.model_dump(mode="json")
                if understanding.window
                else None,
                "understood_by": understanding.understood_by,
                "degraded": understanding.degraded,
                "confidence": understanding.confidence,
                "plan": [p.model_dump(mode="json") for p in understanding.plan],
            },
        )

        # A rejection or a clarification is a complete answer; nothing runs.
        if understanding.status is not UnderstandingStatus.UNDERSTOOD:
            run = await self._executor.execute(understanding, run_id=run_id)
            run.elapsed_ms = int((time.perf_counter() - started) * 1000)
            await record_run(run)
            yield AgentEvent("run", run.model_dump(mode="json"), run=run)
            return

        run: AgentRun | None = None
        total = len(understanding.plan)
        async for kind, item in self._executor.execute_stream(understanding, run_id=run_id):
            if kind == "step":
                yield AgentEvent(
                    "tool_result",
                    {
                        "run_id": run_id,
                        "of": total,
                        **item.model_dump(mode="json", exclude={"detail"}),
                    },
                )
            else:
                run = item

        assert run is not None
        run.elapsed_ms = int((time.perf_counter() - started) * 1000)
        recorded = await record_run(run)
        if not recorded:
            run.notes.append("This run was not written to the audit log.")

        if run.status is RunStatus.ERROR:
            yield AgentEvent("error", {"run_id": run_id, "message": run.answer})

        yield AgentEvent("run", run.model_dump(mode="json"), run=run)


class AgentEvent:
    """One thing that happened, ready to be sent as an SSE frame."""

    __slots__ = ("kind", "payload", "run")

    def __init__(self, kind: str, payload: dict, *, run: AgentRun | None = None) -> None:
        self.kind = kind
        self.payload = payload
        self.run = run
