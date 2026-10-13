"""The repair / replace / escalate policy (Appendix D of the brief).

Precedence (D6), implemented top to bottom in ``decide``:

    1. D5 escalation triggers  -- win over everything
         D5a  >= 2 repairs in 12 months AND negative sentiment
         D5b  a part price or labour_hours is null -> cost cannot be computed
         D5d  symptom text describes a safety hazard
         D5e  symptom text contradicts the structured fields
    2. D3   travel > 120 min AND cost > 40% of replacement -> replace
    3. D4   map warranty "unknown" to in/out of warranty by age (> 24 months)
    4. D1   in_warranty / extended:  D1b lead time > 21 days -> replace;
                                     D1a cost > 60% of replacement -> replace, else repair
       D2   out_of_warranty: repair iff cost <= 50% AND age <= 70% of expected life
    5. D5c  replacement price null AND the decision depends on it -> escalate

How missing inputs are treated (one principle, two cases):

* Override rules and escalation triggers (D3, D1b, D5a) need *positive
  evidence* to fire. If their input is missing they do not fire; confidence is
  lowered and the trace says so. D5 does not list these nulls as escalation
  reasons, so escalating on them would invent policy.
* Base rules (D1a, D2, the D4 mapping) need their inputs to choose between
  repair and replace. A missing input escalates only if filling it in could
  change the answer -- the brief's own wording for D5c ("and the decision
  depends on it"), applied uniformly. Every possible value is considered; if
  all lead to the same decision, we decide.

All comparisons are exact (fractions), and inclusivity follows the brief
literally: "exceeds"/"over" is strict (>), "at most" is <=.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Set

from .cost import CostResult, compute_repair_cost, exact
from .schemas import ServiceCase
from .text import Contradiction, Hazard, find_contradictions, find_safety_hazards

# ---------------------------------------------------------------- thresholds
EXPECTED_LIFE_YEARS = {  # Appendix E
    "washing_machine": 10,
    "refrigerator": 12,
    "dishwasher": 9,
    "oven_or_cooktop": 13,
    "air_conditioner": 10,
    "water_heater": 8,
    "microwave": 8,
}
D1A_MAX_RATIO = Fraction(60, 100)    # replace if cost/replacement  > 60%
D1B_MAX_LEAD_DAYS = 21               # replace if any lead time      > 21 days
D2_MAX_RATIO = Fraction(50, 100)     # repair needs cost/replacement <= 50%
D2_MAX_AGE_FRACTION = Fraction(70, 100)  # ... and age <= 70% of expected life
D3_MIN_TRAVEL_MINUTES = 120          # D3 needs travel               > 120 min
D3_MIN_RATIO = Fraction(40, 100)     # ... and cost/replacement      > 40%
D4_MAX_IN_WARRANTY_AGE = 24          # unknown -> out_of_warranty if age > 24 months
D5A_MIN_PRIOR_REPAIRS = 2            # >= 2 prior repairs + negative sentiment
NEAR_THRESHOLD = Fraction(2, 100)    # D6: within 2 percentage points (absolute)

# ---------------------------------------------------------------- trace for the UI
def _escalation_check_summary(case: ServiceCase, cost: CostResult, hazards: List[Hazard],
                              contradictions: List[Contradiction]) -> List[Dict[str, Any]]:
    """Every D5 trigger with its outcome, for the UI's policy-check list.
    Display only: the decision itself comes from _escalation_triggers."""
    prior = case.prior_repairs_12m
    sentiment = case.customer_sentiment.value if case.customer_sentiment else None
    repeat = prior is not None and prior >= D5A_MIN_PRIOR_REPAIRS and sentiment == "negative"
    if cost.computable:
        cost_detail = "all part prices and labour hours present"
    else:
        missing = cost.missing_part_prices and ["part price: " + ", ".join(cost.missing_part_prices)] or []
        missing += ["labour hours"] if cost.labour_hours_missing else []
        missing += ["labour rate"] if cost.labour_rate_missing else []
        cost_detail = "missing " + "; ".join(missing)
    return [
        {"check": "Safety hazard in symptom text", "triggered": bool(hazards),
         "detail": ", ".join(h.label for h in hazards) if hazards else "none found"},
        {"check": "Symptom text consistent with case fields", "triggered": bool(contradictions),
         "detail": "; ".join(c.detail for c in contradictions) if contradictions else "no conflict found"},
        {"check": "Repeat repairs with negative sentiment", "triggered": repeat,
         "detail": f"{'?' if prior is None else _num(prior)} repairs in 12 months, sentiment {sentiment or 'not given'}"},
        {"check": "Repair cost can be computed", "triggered": not cost.computable, "detail": cost_detail},
    ]


def _stages(stop: str, decision: str, rule: str, case: ServiceCase,
            branches: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """The precedence path (D6) with where this case stopped, for the UI stepper."""
    status = case.warranty_status.value
    if stop == "D5":
        return [
            {"stage": "Escalation checks", "rule": "D5", "status": "stopped", "detail": "escalate"},
            {"stage": "Travel override", "rule": "D3", "status": "skipped", "detail": "not reached"},
            {"stage": "Warranty mapping", "rule": "D4", "status": "skipped", "detail": "not reached"},
            {"stage": "Cost and age rule", "rule": "D1 / D2", "status": "skipped", "detail": "not reached"},
        ]
    stages = [{"stage": "Escalation checks", "rule": "D5", "status": "passed", "detail": "no trigger"}]
    if stop == "D3":
        return stages + [
            {"stage": "Travel override", "rule": "D3", "status": "stopped", "detail": "replace"},
            {"stage": "Warranty mapping", "rule": "D4", "status": "skipped", "detail": "not reached"},
            {"stage": "Cost and age rule", "rule": "D1 / D2", "status": "skipped", "detail": "not reached"},
        ]
    stages.append({"stage": "Travel override", "rule": "D3", "status": "passed", "detail": "not met"})
    if status != "unknown":
        mapping = {"stage": "Warranty mapping", "rule": "D4", "status": "passed",
                   "detail": f"not needed ({status})"}
    elif branches and len(branches) > 1:
        mapping = {"stage": "Warranty mapping", "rule": "D4", "status": "passed",
                   "detail": "age missing: both readings evaluated"}
    else:
        target = "out_of_warranty" if branches and branches[0]["path"] == "D2" else "in_warranty"
        mapping = {"stage": "Warranty mapping", "rule": "D4", "status": "passed", "detail": f"treated as {target}"}
    stages.append(mapping)
    paths = sorted({b["path"] for b in branches or []})
    label = " / ".join(paths) or "D1 / D2"
    if decision == "escalate":
        stages.append({"stage": "Cost and age rule", "rule": label, "status": "stopped",
                       "detail": "missing input decides: escalate"})
    else:
        stages.append({"stage": "Cost and age rule", "rule": rule, "status": "stopped", "detail": decision})
    return stages


# ---------------------------------------------------------------- confidence
# Heuristic, not a calibrated probability. Anchors are the brief's examples
# (0.90 plain repair, 0.85 rule-based replace, 0.70 escalation).
CONF_BASE = {"repair": 0.90, "replace": 0.85, "escalate": 0.70}
CONF_ESCALATE_TEXT_ONLY = 0.60       # only the contradiction heuristic fired
CONF_ESCALATE_UNDETERMINED = 0.65    # missing input makes the policy ambiguous
PENALTY_UNKNOWN_WARRANTY = 0.10      # D4: "Lower the confidence"
PENALTY_NEAR_THRESHOLD = 0.10        # D6: within 2 pp of a deciding threshold
PENALTY_PER_MISSING_INPUT = 0.05     # input missing but did not change the result
MAX_MISSING_PENALTY = 0.10
CONF_FLOOR, CONF_CEIL = 0.40, 0.95


# ---------------------------------------------------------------- data types
@dataclass
class Outcome:
    decision: str                 # "repair" | "replace"
    rule: str                     # e.g. "D1b"
    reason: str                   # one sentence
    depends_on: Set[str] = field(default_factory=set)  # missing inputs behind it


@dataclass
class Result:
    case_id: Any
    decision: str
    estimated_repair_cost: Optional[float]
    confidence: float
    reason: str
    trace: Dict[str, Any]

    def public(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "decision": self.decision,
            "estimated_repair_cost": self.estimated_repair_cost,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class _Ctx:
    case: ServiceCase
    cost: CostResult
    replacement: Optional[Fraction]          # None if missing or not positive
    near: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)  # non-decisive missing inputs
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def note_missing(self, msg: str) -> None:
        if msg not in self.missing:
            self.missing.append(msg)

    def check(self, rule: str, test: str, result: Any) -> None:
        self.checks.append({"rule": rule, "test": test, "result": result})


# ---------------------------------------------------------------- helpers
def _pct(ratio: Fraction) -> str:
    """Whole percent, or one decimal when that is needed to show which side of
    a threshold the value is on (e.g. 60.4%, not "60%")."""
    value = Decimal(ratio.numerator) / Decimal(ratio.denominator) * 100
    whole = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if whole in (40, 50, 60, 70) and value != whole:
        return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"
    return f"{whole}%"


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _ratio(ctx: _Ctx) -> Optional[Fraction]:
    if ctx.replacement is None or ctx.cost.value is None:
        return None
    return ctx.cost.value / ctx.replacement


def _ratio_exceeds(ctx: _Ctx, threshold: Fraction, rule: str) -> Optional[bool]:
    """cost / replacement > threshold; None if replacement price is unusable."""
    r = _ratio(ctx)
    if r is None:
        ctx.check(rule, f"repair cost > {_pct(threshold)} of replacement", "unknown (replacement price missing)")
        return None
    if abs(r - threshold) <= NEAR_THRESHOLD:
        ctx.near.append(f"cost ratio {_pct(r)} is within 2 pp of the {_pct(threshold)} threshold ({rule})")
    result = r > threshold
    ctx.check(rule, f"repair cost {_pct(r)} > {_pct(threshold)} of replacement", result)
    return result


def _expected_life_months(case: ServiceCase) -> Optional[int]:
    if case.product_category is None:
        return None
    return EXPECTED_LIFE_YEARS[case.product_category.value] * 12


def _age_within_life(ctx: _Ctx) -> Optional[bool]:
    """product_age_months <= 70% of expected life; None if age or category missing."""
    life = _expected_life_months(ctx.case)
    age = ctx.case.product_age_months
    if life is None or age is None:
        ctx.check("D2", "age <= 70% of expected life", "unknown (age or product category missing)")
        return None
    fraction = exact(age) / life
    if abs(fraction - D2_MAX_AGE_FRACTION) <= NEAR_THRESHOLD:
        ctx.near.append(f"age is {_pct(fraction)} of expected life, within 2 pp of 70% (D2)")
    result = exact(age) <= D2_MAX_AGE_FRACTION * life
    limit = D2_MAX_AGE_FRACTION * life
    ctx.check("D2", f"age {_num(age)} months <= {_num(float(limit))} months (70% of {life})", result)
    return result


# ---------------------------------------------------------------- rules
def _rule_d3(ctx: _Ctx) -> Optional[Outcome]:
    travel = ctx.case.technician_travel_minutes
    if travel is None:
        ctx.check("D3", "travel > 120 minutes", "unknown (travel missing; rule not applied)")
        return None
    over = travel > D3_MIN_TRAVEL_MINUTES
    ctx.check("D3", f"travel {_num(travel)} > 120 minutes", over)
    if not over:
        return None
    exceeds = _ratio_exceeds(ctx, D3_MIN_RATIO, "D3")
    if exceeds is None:
        ctx.note_missing("replacement price missing, so D3 could not be checked")
        return None
    if not exceeds:
        return None
    return Outcome(
        "replace", "D3",
        f"Technician travel {_num(travel)} minutes exceeds 120 and repair cost "
        f"{_pct(_ratio(ctx))} of replacement exceeds 40%: rule D3.",
    )


def _rule_d1(ctx: _Ctx, label: str) -> List[Outcome]:
    leads = [p.lead_time_days for p in ctx.case.parts]
    known = [x for x in leads if x is not None]
    long_leads = [x for x in known if x > D1B_MAX_LEAD_DAYS]
    ctx.check("D1b", "any part lead time > 21 days",
              bool(long_leads) if long_leads or len(known) == len(leads) else "unknown for some parts")
    if long_leads:
        return [Outcome(
            "replace", "D1b",
            f"{label} and part lead time {_num(max(long_leads))} days exceeds the 21-day limit: rule D1b.",
        )]
    if len(known) < len(leads):
        ctx.note_missing("a part lead time is missing, so D1b could not be fully checked")

    exceeds = _ratio_exceeds(ctx, D1A_MAX_RATIO, "D1a")
    if exceeds is None:
        return [
            Outcome("repair", "D1a", "", {"replacement_price"}),
            Outcome("replace", "D1a", "", {"replacement_price"}),
        ]
    pct = _pct(_ratio(ctx))
    if exceeds:
        return [Outcome("replace", "D1a",
                        f"{label} and repair cost {pct} of replacement exceeds the 60% limit: rule D1a.")]
    return [Outcome("repair", "D1a",
                    f"{label} and repair cost {pct} of replacement is within the 60% limit: rule D1a.")]


def _rule_d2(ctx: _Ctx, label: str) -> List[Outcome]:
    exceeds = _ratio_exceeds(ctx, D2_MAX_RATIO, "D2")
    age_ok = _age_within_life(ctx)
    life = _expected_life_months(ctx.case)

    if exceeds is True:
        return [Outcome("replace", "D2",
                        f"{label}, repair cost {_pct(_ratio(ctx))} of replacement exceeds the 50% limit: rule D2.")]
    if age_ok is False:
        frac = exact(ctx.case.product_age_months) / life
        return [Outcome("replace", "D2",
                        f"{label}, product age {_num(ctx.case.product_age_months)} months is {_pct(frac)} "
                        f"of expected life, over the 70% limit: rule D2.")]
    if exceeds is False and age_ok is True:
        return [Outcome("repair", "D2",
                        f"{label}, repair cost {_pct(_ratio(ctx))} of replacement, "
                        f"age within 70% of expected life: rule D2.")]

    blockers: Set[str] = set()
    if exceeds is None:
        blockers.add("replacement_price")
    if age_ok is None:
        blockers.add("product_age_months" if ctx.case.product_age_months is None else "product_category")
    return [Outcome("repair", "D2", "", blockers), Outcome("replace", "D2", "", blockers)]


def _warranty_branches(ctx: _Ctx) -> List[Dict[str, str]]:
    """Return [{'path': 'D1'|'D2', 'label': ...}] -- two entries if D4 cannot map."""
    status = ctx.case.warranty_status.value
    if status == "in_warranty":
        return [{"path": "D1", "label": "In warranty"}]
    if status == "extended":
        return [{"path": "D1", "label": "Extended warranty"}]
    if status == "out_of_warranty":
        return [{"path": "D2", "label": "Out of warranty"}]

    age = ctx.case.product_age_months
    if age is None:
        ctx.check("D4", "unknown warranty: age > 24 months", "unknown (age missing)")
        return [
            {"path": "D1", "label": "Warranty unknown (treated as in warranty, rule D4)"},
            {"path": "D2", "label": "Warranty unknown (treated as out of warranty, rule D4)"},
        ]
    over = age > D4_MAX_IN_WARRANTY_AGE
    ctx.check("D4", f"unknown warranty: age {_num(age)} > 24 months", over)
    if over:
        return [{"path": "D2",
                 "label": f"Warranty unknown and age {_num(age)} months is over 24, so treated as out of warranty (D4)"}]
    return [{"path": "D1",
             "label": f"Warranty unknown and age {_num(age)} months is 24 or less, so treated as in warranty (D4)"}]


# ---------------------------------------------------------------- escalation
def _escalation_triggers(ctx: _Ctx, hazards: List[Hazard], contradictions: List[Contradiction]) -> List[str]:
    case, cost = ctx.case, ctx.cost
    fragments: List[str] = []

    if hazards:
        labels = " and ".join(h.label for h in hazards)
        fragments.append(f"symptom text reports {labels} (\"{hazards[0].phrase}\"), a safety hazard")

    prior, sentiment = case.prior_repairs_12m, case.customer_sentiment
    sentiment_value = sentiment.value if sentiment else None
    if prior is not None and prior >= D5A_MIN_PRIOR_REPAIRS and sentiment_value == "negative":
        fragments.append(f"{_num(prior)} prior repairs in the last 12 months with negative sentiment")
    elif prior is not None and prior >= D5A_MIN_PRIOR_REPAIRS and sentiment_value is None:
        ctx.note_missing("customer sentiment missing, so D5 repeat-repair check could not be confirmed")
    elif prior is None and sentiment_value == "negative":
        ctx.note_missing("prior repair count missing, so D5 repeat-repair check could not be confirmed")

    if not cost.computable:
        missing = []
        if cost.missing_part_prices:
            missing.append("part price missing for " + ", ".join(cost.missing_part_prices))
        if cost.labour_hours_missing:
            missing.append("labour hours missing")
        if cost.labour_rate_missing:
            missing.append("labour rate missing")
        fragments.append(" and ".join(missing) + " so the repair cannot be costed")

    for c in contradictions:
        fragments.append(f"symptom text contradicts the case fields ({c.detail})")
    return fragments


def _undetermined_reason(blockers: Set[str], unknown_warranty_no_age: bool) -> str:
    parts = []
    if unknown_warranty_no_age:
        parts.append("warranty is unknown and product age is missing, so rule D4 cannot choose "
                     "between in-warranty (D1) and out-of-warranty (D2) treatment")
    if "replacement_price" in blockers:
        parts.append("replacement price is missing and the decision depends on the cost ratio")
    if "product_age_months" in blockers and not unknown_warranty_no_age:
        parts.append("product age is missing and the D2 age test decides the case")
    if "product_category" in blockers:
        parts.append("product category is missing, so the D2 expected-life test cannot be applied")
    return "Escalate (rule D5): " + "; ".join(parts) + ", and the possible answers differ."


# ---------------------------------------------------------------- trace for the UI
def _escalation_check_summary(case: ServiceCase, cost: CostResult, hazards: List[Hazard],
                              contradictions: List[Contradiction]) -> List[Dict[str, Any]]:
    """Every D5 trigger with its outcome, for the UI's policy-check list.
    Display only: the decision itself comes from _escalation_triggers."""
    prior = case.prior_repairs_12m
    sentiment = case.customer_sentiment.value if case.customer_sentiment else None
    repeat = prior is not None and prior >= D5A_MIN_PRIOR_REPAIRS and sentiment == "negative"
    if cost.computable:
        cost_detail = "all part prices and labour hours present"
    else:
        missing = cost.missing_part_prices and ["part price: " + ", ".join(cost.missing_part_prices)] or []
        missing += ["labour hours"] if cost.labour_hours_missing else []
        missing += ["labour rate"] if cost.labour_rate_missing else []
        cost_detail = "missing " + "; ".join(missing)
    return [
        {"check": "Safety hazard in symptom text", "triggered": bool(hazards),
         "detail": ", ".join(h.label for h in hazards) if hazards else "none found"},
        {"check": "Symptom text consistent with case fields", "triggered": bool(contradictions),
         "detail": "; ".join(c.detail for c in contradictions) if contradictions else "no conflict found"},
        {"check": "Repeat repairs with negative sentiment", "triggered": repeat,
         "detail": f"{'?' if prior is None else _num(prior)} repairs in 12 months, sentiment {sentiment or 'not given'}"},
        {"check": "Repair cost can be computed", "triggered": not cost.computable, "detail": cost_detail},
    ]


def _stages(stop: str, decision: str, rule: str, case: ServiceCase,
            branches: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """The precedence path (D6) with where this case stopped, for the UI stepper."""
    status = case.warranty_status.value
    if stop == "D5":
        return [
            {"stage": "Escalation checks", "rule": "D5", "status": "stopped", "detail": "escalate"},
            {"stage": "Travel override", "rule": "D3", "status": "skipped", "detail": "not reached"},
            {"stage": "Warranty mapping", "rule": "D4", "status": "skipped", "detail": "not reached"},
            {"stage": "Cost and age rule", "rule": "D1 / D2", "status": "skipped", "detail": "not reached"},
        ]
    stages = [{"stage": "Escalation checks", "rule": "D5", "status": "passed", "detail": "no trigger"}]
    if stop == "D3":
        return stages + [
            {"stage": "Travel override", "rule": "D3", "status": "stopped", "detail": "replace"},
            {"stage": "Warranty mapping", "rule": "D4", "status": "skipped", "detail": "not reached"},
            {"stage": "Cost and age rule", "rule": "D1 / D2", "status": "skipped", "detail": "not reached"},
        ]
    stages.append({"stage": "Travel override", "rule": "D3", "status": "passed", "detail": "not met"})
    if status != "unknown":
        mapping = {"stage": "Warranty mapping", "rule": "D4", "status": "passed",
                   "detail": f"not needed ({status})"}
    elif branches and len(branches) > 1:
        mapping = {"stage": "Warranty mapping", "rule": "D4", "status": "passed",
                   "detail": "age missing: both readings evaluated"}
    else:
        target = "out_of_warranty" if branches and branches[0]["path"] == "D2" else "in_warranty"
        mapping = {"stage": "Warranty mapping", "rule": "D4", "status": "passed", "detail": f"treated as {target}"}
    stages.append(mapping)
    paths = sorted({b["path"] for b in branches or []})
    label = " / ".join(paths) or "D1 / D2"
    if decision == "escalate":
        stages.append({"stage": "Cost and age rule", "rule": label, "status": "stopped",
                       "detail": "missing input decides: escalate"})
    else:
        stages.append({"stage": "Cost and age rule", "rule": rule, "status": "stopped", "detail": decision})
    return stages


# ---------------------------------------------------------------- confidence
def _confidence(decision: str, ctx: _Ctx, unknown_warranty: bool) -> float:
    c = CONF_BASE[decision]
    if unknown_warranty:
        c -= PENALTY_UNKNOWN_WARRANTY
    if ctx.near:
        c -= PENALTY_NEAR_THRESHOLD
    c -= min(MAX_MISSING_PENALTY, PENALTY_PER_MISSING_INPUT * len(ctx.missing))
    return round(min(CONF_CEIL, max(CONF_FLOOR, c)), 2)


# ---------------------------------------------------------------- entry point
def decide(case: ServiceCase) -> Result:
    cost = compute_repair_cost(case)
    replacement = (
        exact(case.replacement_price)
        if case.replacement_price is not None and case.replacement_price > 0
        else None
    )
    ctx = _Ctx(case=case, cost=cost, replacement=replacement)
    if cost.travel_missing:
        ctx.note_missing("travel minutes missing; cost has no travel component and D3 was not applied")

    product = case.product_category.value if case.product_category else None
    hazards = find_safety_hazards(case.symptom_text, product)
    contradictions = find_contradictions(
        case.symptom_text,
        case.fault_category.value if case.fault_category else None,
        product,
        case.warranty_status.value,
    )
    unknown_warranty = case.warranty_status.value == "unknown"

    trace: Dict[str, Any] = {
        "cost_breakdown": {
            "parts": None if cost.parts_total is None else round(float(cost.parts_total), 2),
            "labour": None if cost.labour is None else round(float(cost.labour), 2),
            "travel": None if cost.travel is None else round(float(cost.travel), 2),
        },
        "cost_to_replacement_ratio": None if _ratio(ctx) is None else round(float(_ratio(ctx)), 4),
        "safety_hazards": [h.kind for h in hazards],
        "contradictions": [c.detail for c in contradictions],
        "checks": ctx.checks,
        "escalation_checks": _escalation_check_summary(case, cost, hazards, contradictions),
    }

    def finish(decision: str, reason: str, rule: str, confidence: float,
               stop: str, branches: Optional[List[Dict[str, str]]] = None) -> Result:
        trace.update({
            "rule": rule,
            "near_threshold": ctx.near,
            "missing_inputs": ctx.missing,
            "stages": _stages(stop, decision, rule, case, branches),
        })
        return Result(case.case_id, decision, cost.rounded(), confidence, reason, trace)

    # 1. D5 triggers win over everything.
    fragments = _escalation_triggers(ctx, hazards, contradictions)
    if fragments:
        text_only = bool(contradictions) and len(fragments) == len(contradictions)
        conf = CONF_ESCALATE_TEXT_ONLY if text_only else CONF_BASE["escalate"]
        reason = "Escalate (rule D5): " + "; ".join(fragments) + "."
        return finish("escalate", reason, "D5", conf, stop="D5")

    # 2. D3 travel override.
    d3 = _rule_d3(ctx)
    if d3:
        return finish("replace", d3.reason, "D3", _confidence("replace", ctx, unknown_warranty), stop="D3")

    # 3-4. D4 mapping, then D1 or D2 on every branch D4 leaves open.
    branches = _warranty_branches(ctx)
    outcomes: List[Outcome] = []
    for b in branches:
        outcomes += _rule_d1(ctx, b["label"]) if b["path"] == "D1" else _rule_d2(ctx, b["label"])

    decisions = {o.decision for o in outcomes}
    if len(decisions) > 1:
        # 5. The answer depends on a missing input (D5c and its generalisation).
        blockers = set().union(*(o.depends_on for o in outcomes))
        reason = _undetermined_reason(blockers, unknown_warranty_no_age=len(branches) > 1)
        return finish("escalate", reason, "D5", CONF_ESCALATE_UNDETERMINED, stop="D1D2", branches=branches)

    decision = decisions.pop()
    definite = [o for o in outcomes if o.reason]
    if len(branches) > 1:
        # D4 could not map the warranty, but both readings agree.
        by_path = {}
        for b, o in zip(branches, definite):
            by_path[b["path"]] = o.rule
        rule = " and ".join(sorted(set(by_path.values())))
        ratio = _ratio(ctx)
        basis = f" (repair cost {_pct(ratio)} of replacement)" if ratio is not None else ""
        reason = (f"Warranty is unknown and product age is missing (rule D4), but in-warranty "
                  f"({by_path['D1']}) and out-of-warranty ({by_path['D2']}) treatment both give "
                  f"{decision}{basis}.")
    else:
        reason, rule = definite[0].reason, definite[0].rule
    return finish(decision, reason, rule, _confidence(decision, ctx, unknown_warranty),
                  stop="D1D2", branches=branches)
