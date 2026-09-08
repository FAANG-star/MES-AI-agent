"""The controlled tool layer.

The LLM never sees the database and never writes SQL (ADR-2). It sees exactly the
tools registered here: a fixed name, a described set of parameters, and a typed
result. Anything the model asks for that is not in this registry simply cannot
happen.

`schemas()` emits the registry in the JSON-schema shape that LLM function calling
expects, so the Day-4 agent hands the model a description generated from the same
Pydantic models the tools validate against — the contract cannot drift.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.repositories.mes_repository import MesRepository
from app.schemas.envelope import ToolResult
from app.timewindow import FactoryClock


class ToolError(Exception):
    """Base for tool-layer failures."""


class UnknownToolError(ToolError):
    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__(f"Unknown tool '{name}'. Available tools: {', '.join(available)}")
        self.name = name
        self.available = available


class ToolNotImplementedError(ToolError):
    def __init__(self, name: str, planned_for: str) -> None:
        super().__init__(f"Tool '{name}' is declared but not implemented yet ({planned_for}).")
        self.name = name
        self.planned_for = planned_for


class ToolParameterError(ToolError):
    def __init__(self, name: str, errors: Any) -> None:
        super().__init__(f"Invalid parameters for '{name}': {errors}")
        self.name = name
        self.errors = errors


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool needs. Injectable, so tests can pin the clock."""

    repo: MesRepository
    clock: FactoryClock


Handler = Callable[[BaseModel, ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params_model: type[BaseModel]
    handler: Handler | None
    implemented: bool = True
    planned_for: str = ""
    scenarios: tuple[str, ...] = field(default_factory=tuple)

    def json_schema(self) -> dict[str, Any]:
        """LLM-facing description, generated from the Pydantic parameter model."""
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
            "implemented": self.implemented,
            "scenarios": list(self.scenarios),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def tool(
        self,
        name: str,
        description: str,
        params_model: type[BaseModel],
        *,
        implemented: bool = True,
        planned_for: str = "",
        scenarios: tuple[str, ...] = (),
    ):
        def decorator(fn: Handler) -> Handler:
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                params_model=params_model,
                handler=fn,
                implemented=implemented,
                planned_for=planned_for,
                scenarios=scenarios,
            )
            return fn

        return decorator

    def declare_planned(
        self,
        name: str,
        description: str,
        params_model: type[BaseModel],
        planned_for: str,
        scenarios: tuple[str, ...] = (),
    ) -> None:
        """Register a tool that exists in the contract but not yet in code.

        The registry stays the single source of truth for all eight tools in
        FR-5; calling one that is not built yet fails loudly and specifically
        rather than silently going missing from the model's options.
        """
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            params_model=params_model,
            handler=None,
            implemented=False,
            planned_for=planned_for,
            scenarios=scenarios,
        )

    def names(self) -> list[str]:
        return sorted(self._tools)

    def implemented_names(self) -> list[str]:
        return sorted(n for n, s in self._tools.items() if s.implemented)

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise UnknownToolError(name, self.names())
        return self._tools[name]

    def schemas(self, *, implemented_only: bool = False) -> list[dict[str, Any]]:
        specs = self._tools.values()
        if implemented_only:
            specs = [s for s in specs if s.implemented]
        return [s.json_schema() for s in sorted(specs, key=lambda s: s.name)]

    async def invoke(self, name: str, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        spec = self.get(name)
        if not spec.implemented or spec.handler is None:
            raise ToolNotImplementedError(name, spec.planned_for or "a later day")
        try:
            parsed = spec.params_model.model_validate(params or {})
        except ValidationError as exc:
            raise ToolParameterError(name, exc.errors()) from exc

        started = time.perf_counter()
        result = await spec.handler(parsed, ctx)
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result


registry = ToolRegistry()
