"""Rule D0: repair-cost arithmetic and null propagation."""

import pytest

from app.cost import compute_repair_cost
from app.schemas import ServiceCase

from .conftest import case, run


def cost_of(**overrides):
    return compute_repair_cost(ServiceCase.model_validate(case(**overrides)))


def test_formula_example_1():
    # 6200 + 1.5*900 + (40/60)*900
    assert cost_of().rounded() == 8150.0


def test_formula_example_2():
    c = cost_of(parts=[{"sku": "x", "price": 14500, "lead_time_days": 28}],
                labour_hours=2.0, technician_travel_minutes=25)
    assert c.rounded() == 16675.0


def test_travel_is_not_doubled():
    # The brief says travel is one way but its formula and examples do not double it.
    c = cost_of(parts=[], labour_hours=0, technician_travel_minutes=60, labour_rate_per_hour=900)
    assert c.rounded() == 900.0


def test_multiple_parts_and_duplicate_skus_are_all_summed():
    parts = [{"sku": "A", "price": 100, "lead_time_days": 1},
             {"sku": "A", "price": 100, "lead_time_days": 1},
             {"sku": "B", "price": 50.5, "lead_time_days": 1}]
    assert cost_of(parts=parts, labour_hours=0, technician_travel_minutes=0).rounded() == 250.5


def test_empty_parts_is_labour_and_travel_only():
    assert cost_of(parts=[], labour_hours=2, technician_travel_minutes=30).rounded() == 2250.0


def test_zero_everything_is_zero_not_null():
    c = cost_of(parts=[], labour_hours=0, technician_travel_minutes=0)
    assert c.computable and c.rounded() == 0.0


def test_null_part_price_makes_cost_uncomputable():
    c = cost_of(parts=[{"sku": "A", "price": None, "lead_time_days": 1},
                       {"sku": "B", "price": 10, "lead_time_days": 1}])
    assert not c.computable and c.missing_part_prices == ["A"]


def test_null_labour_hours_makes_cost_uncomputable():
    c = cost_of(labour_hours=None)
    assert not c.computable and c.labour_hours_missing


def test_null_travel_still_computes_without_travel_component():
    c = cost_of(technician_travel_minutes=None)
    assert c.computable and c.travel_missing
    assert c.rounded() == 6200 + 1.5 * 900


def test_missing_rate_only_matters_when_time_needs_pricing():
    assert not cost_of(labour_rate_per_hour=None).computable
    c = cost_of(labour_rate_per_hour=None, labour_hours=0, technician_travel_minutes=0)
    assert c.computable and c.rounded() == 6200.0


def test_exact_arithmetic_has_no_float_drift():
    # 0.1 + 0.2 style inputs must add exactly.
    parts = [{"sku": "a", "price": 0.1, "lead_time_days": 1}, {"sku": "b", "price": 0.2, "lead_time_days": 1}]
    c = cost_of(parts=parts, labour_hours=0, technician_travel_minutes=0)
    from fractions import Fraction
    assert c.value == Fraction(3, 10)


def test_cost_is_rounded_to_cents_for_output():
    c = cost_of(parts=[], labour_hours=0, technician_travel_minutes=1, labour_rate_per_hour=100)
    assert c.rounded() == 1.67


def test_very_large_values_do_not_overflow():
    r = run(case(parts=[{"sku": "x", "price": 1e12, "lead_time_days": 1}], replacement_price=1e13))
    assert r.estimated_repair_cost == pytest.approx(1e12 + 1350 + 600)
    assert r.decision == "repair"
