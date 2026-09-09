#!/usr/bin/env python
"""Check that the configured local model is good enough to drive the agent.

Model size is not the thing that matters here — **structured-output reliability
is**. The agent extracts every reading into a Pydantic model, so a model that
writes beautiful prose but returns malformed JSON one time in five is unusable,
while a smaller model that always returns valid JSON is fine.

This runs the agent's real prompts against the configured endpoint and reports
what actually happens:

  * is the endpoint reachable and does it have the model
  * which structured-output mode it accepts (json_schema / json_object / prompt)
  * how often extraction produces a schema-valid object, and how often that
    needed a repair round-trip
  * whether the readings are *correct* — the five demo scenarios and the Day-9
    phrasing variants, checked against their expected intent
  * whether the domain guard classifies correctly
  * whether plain completion works, for the Day-7 explainer
  * latency per call

    make llm-check                                   # the full check
    make llm-check ARGS="--quick"                    # scenarios only
    make llm-check ARGS="--model qwen2.5:7b-instruct"  # try another model
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.extractor import (  # noqa: E402
    _EXTRACT_SYSTEM,
    IntentExtractor,
    _intent_guide,
    _rewrite_is_usable,
    _tool_catalogue,
    warm_up,
)
from app.agent.guard import _GUARD_SYSTEM  # noqa: E402
from app.agent.schemas import DomainClassification, ExtractedIntent, Intent  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.base import LLMError  # noqa: E402
from app.llm.factory import build_llm_client  # noqa: E402
from app.llm.openai_compatible import OpenAICompatibleLLMClient  # noqa: E402

SCENARIOS: list[tuple[str, Intent]] = [
    ("How many A12 parts can we produce this week?", Intent.PRODUCTION_CAPACITY),
    ("Can CNC-03 continue production today?", Intent.MACHINE_HEALTH),
    ("Which CNC machine is limiting A12 production?", Intent.BOTTLENECK),
    ("Why was A12 production lower yesterday?", Intent.PRODUCTION_ANALYSIS),
    ("Which machine needs maintenance attention?", Intent.MAINTENANCE_ATTENTION),
    ("What is the current status of CNC-03?", Intent.MACHINE_STATUS),
]

VARIANTS: list[tuple[str, Intent]] = [
    ("What's our A12 output potential this week?", Intent.PRODUCTION_CAPACITY),
    ("Max A12 quantity by Sunday?", Intent.PRODUCTION_CAPACITY),
    ("A12 capacity this week", Intent.PRODUCTION_CAPACITY),
    ("Is CNC-03 safe to run?", Intent.MACHINE_HEALTH),
    ("CNC-03 ok today?", Intent.MACHINE_HEALTH),
    ("Should I keep CNC-03 in production?", Intent.MACHINE_HEALTH),
    ("What's slowing A12 down?", Intent.BOTTLENECK),
    ("A12 bottleneck?", Intent.BOTTLENECK),
    ("Which machine constrains A12 output?", Intent.BOTTLENECK),
    ("A12 was down yesterday, why?", Intent.PRODUCTION_ANALYSIS),
    ("Explain yesterday's A12 shortfall", Intent.PRODUCTION_ANALYSIS),
    ("Yesterday A12 plan vs actual", Intent.PRODUCTION_ANALYSIS),
    ("Any machine needing service?", Intent.MAINTENANCE_ATTENTION),
    ("Which CNC looks unhealthy?", Intent.MAINTENANCE_ATTENTION),
    ("Maintenance priorities", Intent.MAINTENANCE_ATTENTION),
]

GUARD_CASES: list[tuple[str, bool]] = [
    ("Could you look into the situation from Tuesday?", True),
    ("What happened on the shop floor last night?", True),
    ("Can you help me with something personal?", False),
    ("I need a hand with my homework", False),
]

OK, WARN, BAD = "PASS", "WARN", "FAIL"


def line(status: str, text: str) -> None:
    print(f"  [{status}] {text}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick", action="store_true", help="scenarios only, skip variants and guard"
    )
    parser.add_argument("--model", help="override LLM_MODEL, to try a model without editing .env")
    parser.add_argument("--base-url", help="override LLM_BASE_URL")
    args = parser.parse_args()

    settings = get_settings()
    overrides = {
        key: value
        for key, value in (("llm_model", args.model), ("llm_base_url", args.base_url))
        if value
    }
    if overrides:
        settings = settings.model_copy(update=overrides)
    print("=" * 78)
    print("Local LLM readiness check")
    print("=" * 78)
    print(f"  provider : {settings.llm_provider}")
    print(f"  model    : {settings.llm_model}")
    print(f"  endpoint : {settings.llm_base_url or '(n/a)'}")
    print()

    client, reason = build_llm_client(settings)
    if client is None:
        line(BAD, reason)
        print("\nThe agent will run on deterministic rules only.")
        return 1

    failures = 0

    # 1. Reachability -------------------------------------------------------
    print("1. Endpoint")
    if isinstance(client, OpenAICompatibleLLMClient):
        try:
            probe = await client.probe()
        except LLMError as exc:
            line(BAD, str(exc))
            print("\nStart your model server, or set LLM_BASE_URL correctly.")
            await client.aclose()
            return 1
        line(OK, f"reachable — {len(probe['models'])} model(s) served")
        if probe["model_present"]:
            line(OK, f"{settings.llm_model} is available")
        else:
            line(WARN, f"{settings.llm_model} is not in the served list: {probe['models']}")
    else:
        line(OK, "hosted provider configured (development reference)")
    print()

    # 2. Structured output on the real extraction prompt --------------------
    print("2. Structured intent extraction (the agent's real prompt)")
    try:
        warm_start = time.perf_counter()
        warm_client, _ = build_llm_client(
            settings.model_copy(update={"llm_timeout_s": settings.llm_warmup_timeout_s})
        )
        await warm_up(warm_client or client)
        if warm_client is not None:
            await warm_client.aclose()
        print(f"  (warm-up: model + schema ready in {time.perf_counter() - warm_start:.1f}s)")
    except LLMError as exc:
        line(WARN, f"warm-up failed: {str(exc)[:60]}")
    system = _EXTRACT_SYSTEM.format(intent_guide=_intent_guide(), tool_catalogue=_tool_catalogue())
    cases = SCENARIOS if args.quick else SCENARIOS + VARIANTS
    valid = correct = repaired = 0
    raw_entities = raw_rewrites = entities_ok = rewrites_ok = 0
    latencies: list[int] = []

    for question, expected in cases:
        try:
            extracted, usage = await client.structured(
                system=system, user=question, output_model=ExtractedIntent, max_tokens=1024
            )
        except LLMError as exc:
            line(BAD, f"{question[:44]:46} schema failure: {str(exc)[:60]}")
            failures += 1
            continue

        valid += 1
        latencies.append(usage.elapsed_ms)
        if any("repair" in note for note in usage.notes):
            repaired += 1
        hit = extracted.intent is expected
        correct += hit

        # An id named in the question must come back, or an answerable question
        # turns into a needless clarification.
        wanted = {w.strip("?,.") for w in question.replace("'s", "").split()}
        expected_ids = {w.upper() for w in wanted if w.upper() in {"A12", "B20", "C15"}}
        expected_ids |= {w.upper() for w in wanted if w.upper().startswith("CNC-")}

        def ids_found(reading, wanted_ids=expected_ids) -> bool:
            return wanted_ids <= {i.upper() for i in reading.part_ids + reading.machine_ids}

        # Measured twice: what the model produced on its own, and what the
        # pipeline delivers after its pattern-matching safety net. The gap is
        # how much of the work the net is carrying.
        raw_entity_hit = ids_found(extracted)
        raw_entities += raw_entity_hit
        raw_rewrite_hit = _rewrite_is_usable(
            extracted.rewritten_question, extracted.intent, question
        )
        raw_rewrites += raw_rewrite_hit

        delivered = IntentExtractor._sanitise(extracted, question, [])
        entity_hit = ids_found(delivered)
        entities_ok += entity_hit
        rewrite_hit = _rewrite_is_usable(delivered.rewritten_question, delivered.intent, question)
        rewrites_ok += rewrite_hit

        flags = "".join(
            (
                "" if hit else "i",
                "" if entity_hit else "e",
                "" if raw_entity_hit else "n",
                "" if rewrite_hit else "r",
            )
        )
        status = OK if not flags.replace("n", "") else WARN
        detail = f" [{flags}]" if flags else ""
        line(status, f"{question[:44]:46} -> {delivered.intent.value}{detail}")

    total = len(cases)
    print()
    print(f"  schema-valid : {valid}/{total}")
    print(f"  intent match : {correct}/{total}")
    print(f"  entities     : {entities_ok}/{total} delivered ({raw_entities}/{total} model alone)")
    print(f"  rewrites     : {rewrites_ok}/{total} delivered ({raw_rewrites}/{total} model alone)")
    print(f"  repaired     : {repaired}/{total}")
    if latencies:
        median = statistics.median(latencies)
        print(f"  latency      : median {median:.0f} ms, max {max(latencies)} ms")
    if isinstance(client, OpenAICompatibleLLMClient):
        print(f"  mode         : {client.structured_mode}")
    print("  flags: i=intent  e=ids unresolved  n=safety net supplied ids  r=rewrite")
    print()

    # 3. Domain guard -------------------------------------------------------
    guard_correct = guard_total = 0
    if not args.quick:
        print("3. Domain guard (only the cases heuristics cannot settle)")
        for question, expected in GUARD_CASES:
            try:
                verdict, _ = await client.structured(
                    system=_GUARD_SYSTEM,
                    user=f"Request: {question}",
                    output_model=DomainClassification,
                    max_tokens=256,
                )
            except LLMError as exc:
                line(BAD, f"{question[:44]:46} {str(exc)[:50]}")
                failures += 1
                continue
            guard_total += 1
            hit = verdict.in_domain == expected
            guard_correct += hit
            line(OK if hit else WARN, f"{question[:44]:46} -> in_domain={verdict.in_domain}")
        print()

    # 4. Plain completion, for the Day-7 explainer --------------------------
    print("4. Plain completion (Day-7 explainer)")
    try:
        text, usage = await client.complete(
            system=(
                "You explain factory results to a production manager. Use only the numbers given; "
                "never invent or recompute a value."
            ),
            user=(
                "Data: part A12, capacity 3325 units, constraint machine, bottleneck CNC-03 with "
                "50.0 of 72.0 hours available after 22.0 hours of maintenance. "
                "Write two sentences for the factory manager."
            ),
            max_tokens=200,
        )
        if text.strip():
            line(OK, f"{usage.elapsed_ms} ms, {usage.output_tokens} tokens")
            print(f"        {text.strip()[:200]}")
            for number in ("3325", "3,325", "CNC-03"):
                if number in text:
                    line(OK, f"kept the given value {number!r}")
        else:
            line(BAD, "empty completion")
            failures += 1
    except LLMError as exc:
        line(BAD, str(exc)[:70])
        failures += 1
    print()

    # Verdict ---------------------------------------------------------------
    print("=" * 78)
    schema_rate = valid / total if total else 0
    intent_rate = correct / total if total else 0
    entity_rate = entities_ok / total if total else 0
    verdict_ok = (
        schema_rate >= 0.95 and intent_rate >= 0.85 and entity_rate >= 0.95 and failures == 0
    )

    if verdict_ok:
        print(f"READY — {settings.llm_model} is reliable enough to drive the agent.")
    elif schema_rate < 0.95:
        print(f"NOT READY — only {schema_rate:.0%} of replies were schema-valid.")
        print("Structured output is the binding constraint. Try an instruct-tuned model")
        print("known for JSON, lower the temperature, or pin LLM_STRUCTURED_MODE.")
    elif entity_rate < 0.95:
        print(f"MARGINAL — only {entity_rate:.0%} of questions had their ids resolved,")
        print("even after the pattern-matching safety net. Questions naming a part or")
        print("machine would turn into needless clarifications.")
    else:
        print(f"MARGINAL — JSON is reliable but only {intent_rate:.0%} of intents matched.")
        print("A larger instruct model would help. The deterministic fallback still")
        print("covers the documented scenarios, so the demo remains safe.")

    if isinstance(client, OpenAICompatibleLLMClient) and client.structured_mode:
        print(
            f"\nPin this in .env to skip negotiation:  LLM_STRUCTURED_MODE={client.structured_mode}"
        )
    if guard_total:
        print(f"Domain guard on unclear requests: {guard_correct}/{guard_total}")
    print("=" * 78)

    await client.aclose()
    return 0 if verdict_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
