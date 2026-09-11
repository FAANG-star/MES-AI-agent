"""Deterministic calculation and rule engine (FR-6, ADR-3).

Pure functions over typed inputs. No database, no language model, no clock —
which is what makes every number here reproducible and unit-testable against an
exact expected value.
"""

from app.engine.analysis import ProductionAnalysis, analyse_production
from app.engine.bottleneck import ConstraintFinding, identify_constraint
from app.engine.capacity import CapacityResult, CapacityUnavailable, calculate_capacity
from app.engine.rules import MachineHealth, evaluate_machine, rank_attention

__all__ = [
    "CapacityResult",
    "CapacityUnavailable",
    "calculate_capacity",
    "ConstraintFinding",
    "identify_constraint",
    "MachineHealth",
    "evaluate_machine",
    "rank_attention",
    "ProductionAnalysis",
    "analyse_production",
]
