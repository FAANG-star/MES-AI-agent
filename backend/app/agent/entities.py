"""Ground the entities a question mentions against the real MES.

Extraction gives candidate ids; this checks them. It matters for two reasons.

An id the model invented is caught before it can reach an answer. And scenario
R5 — "What is the status of CNC-09?" — needs the reply to name the machines that
*do* exist, which requires asking the factory rather than the model.

This runs after the domain guard, so a rejected request still touches no data.
Resolution is plain repository code; the model is not involved and never sees a
table.
"""

from __future__ import annotations

import re

from app.agent.schemas import EntityRef, ResolvedEntities
from app.repositories.mes_repository import MesRepository


def normalise_machine_id(raw: str) -> str:
    """'cnc 3' / 'CNC3' / 'cnc-3' all mean CNC-03."""
    match = re.fullmatch(r"\s*CNC[-\s]?(\d{1,3})\s*", raw, flags=re.IGNORECASE)
    if match:
        return f"CNC-{int(match.group(1)):02d}"
    return raw.strip().upper()


class EntityResolver:
    def __init__(self, repo: MesRepository) -> None:
        self._repo = repo

    async def resolve(
        self,
        *,
        part_ids: list[str],
        machine_ids: list[str],
        material_ids: list[str],
    ) -> ResolvedEntities:
        known_parts = await self._repo.part_ids()
        known_machines = await self._repo.machine_ids()
        known_materials = [item.material_id for item in await self._repo.inventory()]

        resolved = ResolvedEntities(
            known_part_ids=known_parts,
            known_machine_ids=known_machines,
        )

        for raw in _unique(part_ids):
            entity_id = raw.strip().upper()
            ref = EntityRef(id=entity_id, kind="part", exists=entity_id in known_parts)
            resolved.parts.append(ref)
            if not ref.exists:
                resolved.unknown.append(ref)

        for raw in _unique(machine_ids):
            entity_id = normalise_machine_id(raw)
            ref = EntityRef(id=entity_id, kind="machine", exists=entity_id in known_machines)
            resolved.machines.append(ref)
            if not ref.exists:
                resolved.unknown.append(ref)

        for raw in _unique(material_ids):
            entity_id = raw.strip().upper()
            ref = EntityRef(id=entity_id, kind="material", exists=entity_id in known_materials)
            resolved.materials.append(ref)
            if not ref.exists:
                resolved.unknown.append(ref)

        return resolved


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().upper()
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
