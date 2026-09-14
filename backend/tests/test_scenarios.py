"""The demo script, run as a test, on the deterministic path.

Every case in docs/04-demo-scenarios.md — the five scenarios, the brief's own
demo phrasing, all fifteen phrasing variants and the reliability cases — is
asked through the real pipeline against the seeded factory, with no language
model, and checked against the SQL oracle (scenarios/matrix.py).

This is the floor: if a scenario fails here, it fails for everyone, whatever
model is attached. The same matrix runs against the live stack and the local
model with `make scenarios`, which is where model-specific mistakes appear.
Because `make test-week` runs this file once as each day of the week, "the demo
works" is a claim about every day, not the day the test happened to run.
"""

from __future__ import annotations

import pytest

from app.agent.pipeline import AgentPipeline
from app.config import get_settings
from scenarios.matrix import BY_ID, CASES, evaluate, load_oracle
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def oracle(pool):
    async with pool.acquire() as conn:
        return await load_oracle(conn, get_settings().factory_clock().today())


@pytest.fixture
def agent(repo):
    return AgentPipeline(repo=repo, clock=get_settings().factory_clock(), llm=None)


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_the_demo_script(case, agent, oracle):
    run = (await agent.ask(case.question)).model_dump(mode="json")
    base = None
    if case.base:
        base = (await agent.ask(BY_ID[case.base].question)).model_dump(mode="json")

    failures = evaluate(case, run, oracle, base)
    assert not failures, f"{case.id} · {case.question}\n  " + "\n  ".join(failures)


async def test_the_matrix_covers_the_whole_script():
    """Coverage of docs/04, stated so that dropping a case is a visible change."""
    groups = {}
    for case in CASES:
        groups.setdefault(case.group, []).append(case.id)

    assert {"S1", "S2", "S3", "S4", "S5"} <= set(groups["scenario"])
    assert len(groups["variant"]) == 15, "docs/04 lists three variants per scenario"
    assert {"D1", "D3", "D4"} <= set(groups["demo"])
    assert {"R1", "R2", "R3", "R4", "R5", "R8", "R9"} <= set(groups["reliability"])


async def test_asking_twice_returns_the_same_findings(agent, oracle):
    """S1 pass criterion 4: re-asking returns the identical number."""
    first = (await agent.ask(BY_ID["S1"].question)).model_dump(mode="json")
    second = (await agent.ask(BY_ID["S1"].question)).model_dump(mode="json")
    assert first["headline"] == second["headline"]
    assert first["bottleneck"] == second["bottleneck"]
    assert first["capacity"]["formula"] == second["capacity"]["formula"]


# --------------------------------------------------- the harness can fail


async def test_a_wrong_capacity_is_caught(agent, oracle):
    """A matrix that cannot fail proves nothing. Each of these is a real failure
    mode from this project's history, applied to a correct run."""
    run = (await agent.ask(BY_ID["S1"].question)).model_dump(mode="json")
    one_machine = next(m["parts_possible"] for m in run["capacity"]["machines"] if m["eligible"])
    run["headline"]["value"] = one_machine  # the "317 A12 parts" failure
    assert any("headline" in f for f in evaluate(BY_ID["S1"], run, oracle))


async def test_a_wrong_tool_sequence_is_caught(agent, oracle):
    run = (await agent.ask(BY_ID["S1"].question)).model_dump(mode="json")
    run["steps"] = [s for s in run["steps"] if s["tool"] != "get_material_inventory"]
    assert any(f.startswith("tools") for f in evaluate(BY_ID["S1"], run, oracle))


async def test_a_wrong_bottleneck_is_caught(agent, oracle):
    run = (await agent.ask(BY_ID["S3"].question)).model_dump(mode="json")
    run["bottleneck"]["machine_id"] = "CNC-01"
    assert any("bottleneck" in f for f in evaluate(BY_ID["S3"], run, oracle))


async def test_an_ungrounded_answer_is_caught(agent, oracle):
    run = (await agent.ask(BY_ID["S5"].question)).model_dump(mode="json")
    run["validation"]["grounded"] = False
    assert any(f.startswith("grounded") for f in evaluate(BY_ID["S5"], run, oracle))


async def test_a_variant_that_drifts_from_its_base_is_caught(agent, oracle):
    base = (await agent.ask(BY_ID["S1"].question)).model_dump(mode="json")
    variant = (await agent.ask(BY_ID["S1c"].question)).model_dump(mode="json")
    variant["headline"]["value"] = base["headline"]["value"] + 1
    failures = evaluate(BY_ID["S1c"], variant, oracle, base)
    assert any("differs from S1" in f for f in failures)


async def test_a_rejection_that_read_the_factory_is_caught(agent, oracle):
    run = (await agent.ask(BY_ID["R4"].question)).model_dump(mode="json")
    run["tool_call_count"] = 1
    assert any("tool calls" in f for f in evaluate(BY_ID["R4"], run, oracle))
