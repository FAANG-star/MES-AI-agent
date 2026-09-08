"""The typed envelope every MES tool returns.

FR-5 fixes the contract as `{data, sources[], missing_fields[], warnings[]}`.
Three fields are added, each earning its place:

  * `not_found`   — asked-for entities that do not exist in the MES. Scenario R5
                    ("What is the status of CNC-09?") must answer "CNC-09 does not
                    exist", and structured data beats parsing a warning string.
  * `window`      — the concrete dates the tool actually used, so an answer can
                    say *which* week it means.
  * `tool`/`ok`/`elapsed_ms` — trace metadata for the audit log and the UI's
                    "AI Analysis Steps".

`missing_fields` is the backbone of FR-8: a NULL in the MES means *unknown*, and
the tool says so explicitly instead of returning a silent null that the LLM might
paper over with a plausible number.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.timewindow import ResolvedWindow

T = TypeVar("T")


class SourceRef(BaseModel):
    """One factory data source that contributed to a result — the "Data Used" list."""

    table: str
    fields: list[str] = Field(default_factory=list)
    keys: list[str] = Field(default_factory=list, description="Entity ids read, e.g. ['A12']")
    rows: int = 0


class MissingField(BaseModel):
    """A required value the MES does not have. Never estimated, never defaulted."""

    entity: str = Field(description="The entity it belongs to, e.g. 'B20'")
    field: str = Field(description="Fully qualified column, e.g. 'parts.cycle_time_min'")
    reason: str = Field(description="Plain-language explanation for the factory manager")


class ToolResult(BaseModel, Generic[T]):
    tool: str
    ok: bool = True
    data: T | None = None
    window: ResolvedWindow | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    missing_fields: list[MissingField] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: int | None = None

    @property
    def has_missing_data(self) -> bool:
        return bool(self.missing_fields)
