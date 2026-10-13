"""Rule D0: estimated repair cost.

    cost = sum(part.price) + labour_hours * rate + (travel_minutes / 60) * rate

Notes that matter for correctness:

* The brief says travel is one way and "the formula already allows for the
  return", yet the formula and both worked examples use minutes / 60 * rate
  with no doubling (C-2001: 40 min -> 600.0). We follow the formula and the
  examples exactly.
* D0 names exactly two nulls that make the cost uncomputable: any part price,
  or labour_hours. A missing labour rate is a third, structural case (there is
  nothing to multiply by) unless no labour or travel time needs pricing.
* Null travel minutes is NOT in that list, so the cost is still computed with
  no travel component, and the trace flags it. (NOTES.md, decision 2.)
* All arithmetic is exact (``fractions.Fraction`` built from the decimal text
  of each input), so a cost of exactly 60% of the replacement price compares
  as exactly 60%, not 60.0000000001%. Rounding happens only for output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import List, Optional

from .schemas import ServiceCase


def exact(value: float) -> Fraction:
    """Convert a JSON number to the exact rational a human typed (0.1 -> 1/10)."""
    return Fraction(Decimal(repr(float(value))))


@dataclass
class CostResult:
    value: Optional[Fraction]          # None when the cost cannot be computed
    parts_total: Optional[Fraction] = None
    labour: Optional[Fraction] = None
    travel: Optional[Fraction] = None
    missing_part_prices: List[str] = field(default_factory=list)  # SKUs / labels
    labour_hours_missing: bool = False
    labour_rate_missing: bool = False
    travel_missing: bool = False

    @property
    def computable(self) -> bool:
        return self.value is not None

    def rounded(self) -> Optional[float]:
        return None if self.value is None else round(float(self.value), 2)


def compute_repair_cost(case: ServiceCase) -> CostResult:
    missing_prices = [
        (p.sku or p.description or f"part #{i + 1}")
        for i, p in enumerate(case.parts)
        if p.price is None
    ]
    parts_total = (
        None if missing_prices else sum((exact(p.price) for p in case.parts), Fraction(0))
    )

    travel_missing = case.technician_travel_minutes is None
    travel_minutes = Fraction(0) if travel_missing else exact(case.technician_travel_minutes)
    labour_hours_missing = case.labour_hours is None

    rate_missing = case.labour_rate_per_hour is None
    # The rate is only needed if there is labour or travel time to price.
    rate_needed = labour_hours_missing or (case.labour_hours or 0) > 0 or travel_minutes > 0
    labour_rate_missing = rate_missing and rate_needed
    rate = Fraction(0) if rate_missing else exact(case.labour_rate_per_hour)

    labour = None if labour_hours_missing or labour_rate_missing else exact(case.labour_hours) * rate
    travel = None if labour_rate_missing else travel_minutes / 60 * rate

    value = None
    if parts_total is not None and labour is not None and travel is not None:
        value = parts_total + labour + travel

    return CostResult(
        value=value,
        parts_total=parts_total,
        labour=labour,
        travel=travel,
        missing_part_prices=missing_prices,
        labour_hours_missing=labour_hours_missing,
        labour_rate_missing=labour_rate_missing,
        travel_missing=travel_missing,
    )
