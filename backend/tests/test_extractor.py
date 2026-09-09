"""Request rewriting and structured intent extraction (FR-2, FR-3)."""

from __future__ import annotations

import pytest

from app.agent.extractor import IntentExtractor, extract_with_rules
from app.agent.schemas import ExtractedIntent, Intent, Metric
from app.llm.base import LLMClient, LLMError, LLMUsage

SCENARIOS = [
    ("How many A12 parts can we produce this week?", Intent.PRODUCTION_CAPACITY),
    ("Can CNC-03 continue production today?", Intent.MACHINE_HEALTH),
    ("Which CNC machine is limiting A12 production?", Intent.BOTTLENECK),
    ("Why was A12 production lower yesterday?", Intent.PRODUCTION_ANALYSIS),
    ("Which machine needs maintenance attention?", Intent.MAINTENANCE_ATTENTION),
    ("What is the current status of CNC-03?", Intent.MACHINE_STATUS),
]

VARIANTS = [
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


class ScriptedLLM(LLMClient):
    name = "scripted"

    def __init__(self, result: ExtractedIntent | None = None, fail: bool = False) -> None:
        self._result = result
        self._fail = fail
        self.prompts: list[str] = []

    async def structured(self, *, system, user, output_model, max_tokens=2048):
        self.prompts.append(system)
        if self._fail:
            raise LLMError("provider unreachable")
        return self._result, LLMUsage(provider=self.name)

    async def complete(self, *, system, user, max_tokens=1024):
        return "", LLMUsage()


@pytest.mark.parametrize(("question", "expected"), SCENARIOS)
def test_the_five_demo_scenarios_are_classified(question, expected):
    assert extract_with_rules(question).intent is expected


@pytest.mark.parametrize(("question", "expected"), VARIANTS)
def test_phrasing_variants_reach_the_same_intent(question, expected):
    assert extract_with_rules(question).intent is expected


def test_past_tense_questions_are_analysis_not_capacity():
    """The ordering trap: 'why was production lower' contains 'production'."""
    assert (
        extract_with_rules("Why was A12 production lower yesterday?").intent
        is Intent.PRODUCTION_ANALYSIS
    )


def test_time_windows_are_read_from_the_wording():
    assert extract_with_rules("How many A12 can we produce this week?").time_window == "this_week"
    assert extract_with_rules("How many A12 parts tomorrow?").time_window == "tomorrow"
    assert extract_with_rules("Why was A12 output lower yesterday?").time_window == "yesterday"
    assert extract_with_rules("A12 capacity next week").time_window == "next_week"


def test_intent_supplies_a_default_window_when_none_is_stated():
    assert extract_with_rules("Can CNC-03 continue production?").time_window == "today"
    assert (
        extract_with_rules("Which CNC machine is limiting A12 production?").time_window
        == "this_week"
    )


def test_entities_are_picked_out_of_the_wording():
    extracted = extract_with_rules("How many A12 parts can CNC-03 produce this week?")
    assert extracted.part_ids == ["A12"]
    assert extracted.machine_ids == ["CNC-03"]


def test_a_machine_id_is_not_mistaken_for_a_part_code():
    assert extract_with_rules("What is the status of CNC-03?").part_ids == []


def test_an_elliptical_question_is_rewritten_in_full():
    """Scenario R1."""
    extracted = extract_with_rules("How many A12 this week?")
    assert extracted.intent is Intent.PRODUCTION_CAPACITY
    assert not extracted.ambiguous
    rewrite = extracted.rewritten_question.lower()
    assert "maximum feasible" in rewrite and "a12" in rewrite


def test_a_quantity_question_with_no_period_or_metric_is_ambiguous():
    """Scenario R2 — capacity, plan and actual are three different numbers."""
    extracted = extract_with_rules("How many A12?")
    assert extracted.ambiguous
    assert len(extracted.clarification_options) >= 3


def test_a_planned_quantity_question_is_an_order_lookup_not_a_capacity_calculation():
    """The planned number lives in production_orders; capacity is a different question."""
    extracted = extract_with_rules("What is the planned A12 quantity?")
    assert extracted.intent is Intent.PRODUCTION_ORDERS
    assert extracted.metric is Metric.PLANNED_PRODUCTION
    assert not extracted.ambiguous


def test_naming_the_metric_resolves_a_bare_quantity_question():
    assert extract_with_rules("How many A12?").ambiguous
    assert not extract_with_rules("What is the maximum A12 capacity this week?").ambiguous


def test_an_unrecognised_question_is_ambiguous_not_guessed():
    extracted = extract_with_rules("Tell me about the thing")
    assert extracted.intent is Intent.UNKNOWN and extracted.ambiguous


async def test_the_model_path_is_used_when_a_provider_exists():
    scripted = ScriptedLLM(
        ExtractedIntent(
            rewritten_question=(
                "Calculate maximum feasible A12 production for the current ISO week."
            ),
            intent=Intent.PRODUCTION_CAPACITY,
            metric=Metric.MAX_CAPACITY,
            part_ids=["A12"],
            time_window="this_week",
            required_tools=["get_part_information"],
            confidence=0.94,
        )
    )
    extracted, path, usage, notes = await IntentExtractor(scripted).extract(
        "How many A12 this week?"
    )
    assert path == "llm" and usage.provider == "scripted"
    assert extracted.confidence == 0.94
    assert notes == []


async def test_the_model_is_given_the_real_tool_catalogue():
    scripted = ScriptedLLM(ExtractedIntent(rewritten_question="x", intent=Intent.UNKNOWN))
    await IntentExtractor(scripted).extract("anything")
    system = scripted.prompts[0]
    assert "get_part_information" in system and "calculate_production_capacity" in system


async def test_a_tool_name_the_mes_does_not_have_is_dropped_and_noted():
    scripted = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="x",
            intent=Intent.PRODUCTION_CAPACITY,
            part_ids=["A12"],
            required_tools=["get_part_information", "run_raw_sql"],
        )
    )
    extracted, _, _, notes = await IntentExtractor(scripted).extract("How many A12 this week?")
    assert extracted.required_tools == ["get_part_information"]
    assert any("run_raw_sql" in note for note in notes)


async def test_a_provider_failure_falls_back_to_rules_and_says_so():
    extracted, path, usage, notes = await IntentExtractor(ScriptedLLM(fail=True)).extract(
        "How many A12 parts can we produce this week?"
    )
    assert path == "rules" and usage is None
    assert extracted.intent is Intent.PRODUCTION_CAPACITY
    assert any("unavailable" in note for note in notes)


async def test_rules_are_used_when_no_provider_is_configured():
    _, path, usage, _ = await IntentExtractor(None).extract("A12 capacity this week")
    assert path == "rules" and usage is None


# --------------------------------------------- deterministic floors over the model


class FixedLLM(ScriptedLLM):
    """A model that returns whatever the test says it does."""


async def test_a_stated_time_window_overrides_the_models_choice():
    """A wrong window silently changes every number downstream."""
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="Explain why A12 production differed from plan for this week.",
            intent=Intent.PRODUCTION_ANALYSIS,
            part_ids=["A12"],
            time_window="this_week",  # the model got it wrong
        )
    )
    extracted, _, _, notes = await IntentExtractor(llm).extract(
        "Why was A12 production lower yesterday?"
    )
    assert extracted.time_window == "yesterday"
    assert any("corrected" in note for note in notes)


async def test_the_model_still_chooses_the_window_when_none_is_stated():
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="Identify which machine limits A12 production next week.",
            intent=Intent.BOTTLENECK,
            part_ids=["A12"],
            time_window="next_week",
        )
    )
    extracted, _, _, _ = await IntentExtractor(llm).extract("Which machine is limiting A12?")
    assert extracted.time_window == "next_week"


async def test_ids_in_the_question_are_recovered_when_the_model_misses_them():
    """A 3B model returns the right intent and no entities at all."""
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="Calculate the maximum feasible A12 production for this week.",
            intent=Intent.PRODUCTION_CAPACITY,
            part_ids=[],
            machine_ids=[],
        )
    )
    extracted, _, _, _ = await IntentExtractor(llm).extract(
        "How many A12 parts can CNC-03 produce this week?"
    )
    assert extracted.part_ids == ["A12"]
    assert extracted.machine_ids == ["CNC-03"]


async def test_the_models_entities_are_kept_not_replaced():
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="Report the status of CNC-05 and CNC-01.",
            intent=Intent.MACHINE_STATUS,
            machine_ids=["CNC-05"],
        )
    )
    extracted, _, _, _ = await IntentExtractor(llm).extract("How is CNC-01 doing?")
    assert extracted.machine_ids == ["CNC-05", "CNC-01"]


async def test_a_bare_quantity_question_is_forced_to_clarify():
    """Scenario R2: a model that quietly assumes a period must be overruled."""
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="Calculate the maximum feasible A12 production for this week.",
            intent=Intent.PRODUCTION_CAPACITY,
            part_ids=["A12"],
            time_window="this_week",
            ambiguous=False,  # the model assumed
        )
    )
    extracted, _, _, notes = await IntentExtractor(llm).extract("How many A12?")
    assert extracted.ambiguous
    assert extracted.clarification_options
    assert any("ambiguous" in note for note in notes)


async def test_a_degenerate_rewrite_is_replaced():
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="production_analysis: Why was A12 production lower yesterday?",
            intent=Intent.PRODUCTION_ANALYSIS,
            part_ids=["A12"],
            time_window="yesterday",
        )
    )
    extracted, _, _, _ = await IntentExtractor(llm).extract(
        "Why was A12 production lower yesterday?"
    )
    assert "production_analysis" not in extracted.rewritten_question
    assert "A12" in extracted.rewritten_question


async def test_a_truncated_rewrite_is_replaced():
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="How many can we produce",
            intent=Intent.PRODUCTION_CAPACITY,
            part_ids=["A12"],
            time_window="this_week",
        )
    )
    extracted, _, _, _ = await IntentExtractor(llm).extract(
        "How many A12 parts can we produce this week?"
    )
    assert "maximum feasible" in extracted.rewritten_question.lower()


async def test_a_good_rewrite_from_the_model_is_kept():
    good = "Calculate the maximum feasible A12 production quantity for the current ISO week."
    llm = ScriptedLLM(
        ExtractedIntent(
            rewritten_question=good,
            intent=Intent.PRODUCTION_CAPACITY,
            part_ids=["A12"],
            time_window="this_week",
        )
    )
    extracted, _, _, _ = await IntentExtractor(llm).extract(
        "How many A12 parts can we produce this week?"
    )
    assert extracted.rewritten_question == good
