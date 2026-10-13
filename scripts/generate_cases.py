"""Deterministic synthetic test corpus.

Each case is built from a *scenario* whose expected decision is fixed by
construction from the brief's rules (e.g. "out of warranty, cost 52-95% of
replacement" -> replace). Labels are NOT produced by running app/policy.py, so
evaluating the engine on this corpus checks it against the written policy, not
against itself. Expected costs are computed here with plain float arithmetic,
independently of app/cost.py.

    python scripts/generate_cases.py              # writes data/synthetic_cases.jsonl
    python scripts/generate_cases.py --seed 7 --per-scenario 100

See DATA.md for the scenario list and what this corpus cannot tell you.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_SEED = 2026
DEFAULT_PER_SCENARIO = 40

LIFE = {"washing_machine": 10, "refrigerator": 12, "dishwasher": 9, "oven_or_cooktop": 13,
        "air_conditioner": 10, "water_heater": 8, "microwave": 8}

# Consistent symptom wording per product, phrased differently from the unit tests.
CLEAN_TEXT: Dict[str, List[Tuple[str, str]]] = {
    "washing_machine": [("motor_or_drive", "drum stuck, wont spin on any program"),
                        ("drainage_or_blockage", "water sitting in drum after cycle, pump choked"),
                        ("noise_or_vibration", "machine shakes and bangs during spin"),
                        ("door_seal_or_latch", "door latch broken, door won't lock")],
    "refrigerator": [("not_cooling", "freezer side thawing, milk going off"),
                     ("not_cooling", "compressor runs but cabinet is warm"),
                     ("door_seal_or_latch", "door gasket torn at the bottom"),
                     ("noise_or_vibration", "loud buzzing from the back at night")],
    "dishwasher": [("water_leak", "water dripping under the unit after each wash"),
                   ("drainage_or_blockage", "dirty water left in the base, won't drain"),
                   ("not_heating", "dishes come out cold, no heating"),
                   ("control_panel_or_display", "buttons on the panel do nothing")],
    "oven_or_cooktop": [("not_heating", "oven never gets hot, bake element dead cold"),
                        ("control_panel_or_display", "display flashes and keypad unresponsive"),
                        ("door_seal_or_latch", "oven door hinge loose, door hangs open")],
    "air_conditioner": [("not_cooling", "AC blowing warm air since Monday"),
                        ("water_leak", "water dripping from the indoor unit"),
                        ("noise_or_vibration", "rattling sound from outdoor unit")],
    "water_heater": [("not_heating", "geyser gives only lukewarm water"),
                     ("water_leak", "tank leaking from the bottom"),
                     ("electrical_or_control_board", "keeps tripping the MCB when switched on")],
    "microwave": [("not_heating", "runs but food stays cold"),
                  ("door_seal_or_latch", "door won't latch, stops mid cycle"),
                  ("control_panel_or_display", "touch pad not responding")],
}
HAZARD_TEXT = [
    "technician saw sparking at the terminal block",
    "a puff of smoke came out of the back panel",
    "kitchen smelled of gas after using it",
    "the casing gave my son a shock",
    "flames seen behind the control panel",
    "there is a smell of burning plastic when it runs",
    "it caught fire briefly before we unplugged it",
]
NEGATED_HAZARD_SUFFIX = [
    "; no smoke or sparks seen",
    ", no burning smell",
    ". Customer confirms there was no smoke.",
    ", without any sparking",
]
# (declared fault, text that clearly describes a different, incompatible fault)
CONTRADICTIONS = [
    ("not_cooling", "door will not shut properly"),
    ("water_leak", "screen is blank and keypad dead"),
    ("noise_or_vibration", "door seal is torn"),
    ("door_seal_or_latch", "terrible grinding noise on spin"),
    ("control_panel_or_display", "puddle of water forms under it"),
    ("not_heating", "door latch snapped off"),
]


class Gen:
    def __init__(self, rng: random.Random):
        self.rng = rng

    # --------------------------------------------------------------- building blocks
    def base(self, warranty: str, ratio_range: Tuple[float, float], *, travel=(10, 110),
             age_fraction=(0.05, 0.68), lead=(1, 21), product: Optional[str] = None) -> Dict[str, Any]:
        r = self.rng
        product = product or r.choice(sorted(LIFE))
        fault, text = r.choice(CLEAN_TEXT[product])
        life_months = LIFE[product] * 12
        for _ in range(1000):
            rate = r.choice([500, 600, 750, 900, 1200])
            hours = r.choice([0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
            minutes = r.randint(*travel)
            replacement = r.randrange(15000, 90001, 500)
            target = r.uniform(*ratio_range)
            fixed = hours * rate + minutes / 60 * rate
            part_total = round(target * replacement - fixed)
            if part_total < 0:
                continue
            cost = part_total + fixed
            if ratio_range[0] <= cost / replacement <= ratio_range[1]:
                break
        else:  # pragma: no cover
            raise RuntimeError("could not satisfy ratio range")
        n_parts = r.choice([1, 1, 1, 2])
        split = [part_total] if n_parts == 1 else [part_total // 2, part_total - part_total // 2]
        parts = [{"sku": f"SKU-{r.randint(100, 999)}", "description": "replacement part",
                  "price": p, "lead_time_days": r.randint(*lead)} for p in split]
        age = max(0, int(r.uniform(*age_fraction) * life_months))
        return {
            "case_id": "",
            "product_category": product,
            "product_age_months": age,
            "purchase_price": round(replacement * r.uniform(0.8, 1.2)),
            "replacement_price": replacement,
            "warranty_status": warranty,
            "fault_category": fault,
            "parts": parts,
            "labour_hours": hours,
            "labour_rate_per_hour": rate,
            "technician_travel_minutes": minutes,
            "prior_repairs_12m": r.choice([0, 0, 0, 1]),
            "customer_sentiment": r.choice(["neutral", "positive", "negative"]),
            "symptom_text": text,
        }

    def noisy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """Format noise the hidden set might contain: casing, spaces, numeric strings."""
        r = self.rng
        if r.random() < 0.2:
            case["warranty_status"] = case["warranty_status"].replace("_", " ").title()
        if r.random() < 0.15:
            case["product_category"] = case["product_category"].replace("_", " ").upper()
        if r.random() < 0.1 and case["replacement_price"] is not None:
            case["replacement_price"] = f"{case['replacement_price']:,}"
        if r.random() < 0.2:
            case.pop("purchase_price", None)
        return case


def expected_cost(case: Dict[str, Any]) -> Optional[float]:
    def num(v):
        return float(str(v).replace(",", "")) if v is not None else None
    if any(p["price"] is None for p in case["parts"]) or case["labour_hours"] is None:
        return None
    rate = num(case["labour_rate_per_hour"])
    travel = num(case["technician_travel_minutes"]) or 0.0
    return round(sum(num(p["price"]) for p in case["parts"]) + case["labour_hours"] * rate + travel / 60 * rate, 2)


# ------------------------------------------------------------------- scenarios
Scenario = Callable[[Gen], Tuple[Dict[str, Any], str]]


def oow_repair(g):            return g.base("out_of_warranty", (0.05, 0.47)), "repair"
def oow_replace_cost(g):      return g.base("out_of_warranty", (0.53, 0.95)), "replace"
def oow_replace_age(g):       return g.base("out_of_warranty", (0.05, 0.45), age_fraction=(0.73, 1.5)), "replace"
def iw_repair(g):             return g.base(g.rng.choice(["in_warranty", "extended"]), (0.05, 0.57)), "repair"
def iw_replace_cost(g):       return g.base(g.rng.choice(["in_warranty", "extended"]), (0.63, 0.98)), "replace"
def iw_replace_lead(g):       return g.base("in_warranty", (0.05, 0.55), lead=(22, 60)), "replace"
def d3_replace(g):            return g.base("in_warranty", (0.43, 0.57), travel=(121, 240)), "replace"
def d3_not_applicable(g):     return g.base("in_warranty", (0.05, 0.37), travel=(121, 240)), "repair"


def unknown_young(g):
    c = g.base("unknown", (0.52, 0.57))
    c["product_age_months"] = g.rng.randint(0, 24)
    return c, "repair"            # D4 -> in warranty -> D1a (<= 60%)


def unknown_old(g):
    c = g.base("unknown", (0.52, 0.57), product="refrigerator")
    c["product_age_months"] = g.rng.randint(25, 100)   # <= 70% of 144 months
    return c, "replace"           # D4 -> out of warranty -> D2 (> 50%)


def esc_repeat_negative(g):
    c = g.base(g.rng.choice(["in_warranty", "out_of_warranty"]), (0.05, 0.4))
    c.update(prior_repairs_12m=g.rng.randint(2, 5), customer_sentiment="negative")
    return c, "escalate"


def esc_null_part_price(g):
    c = g.base("out_of_warranty", (0.05, 0.4))
    c["parts"][0]["price"] = None
    return c, "escalate"


def esc_null_labour(g):
    c = g.base("in_warranty", (0.05, 0.4))
    c["labour_hours"] = None
    return c, "escalate"


def esc_null_replacement(g):
    c = g.base("in_warranty", (0.05, 0.4))
    c["replacement_price"] = None
    return c, "escalate"


def replace_null_replacement_long_lead(g):
    c = g.base("extended", (0.05, 0.4), lead=(25, 45))
    c["replacement_price"] = None
    return c, "replace"


def esc_hazard(g):
    c = g.base("in_warranty", (0.05, 0.4))
    c["symptom_text"] = g.rng.choice(HAZARD_TEXT)
    c["fault_category"] = "other"
    return c, "escalate"


def negated_hazard_repair(g):
    c = g.base("out_of_warranty", (0.05, 0.4))
    c["symptom_text"] += g.rng.choice(NEGATED_HAZARD_SUFFIX)
    return c, "repair"


def esc_contradiction(g):
    c = g.base("in_warranty", (0.05, 0.4), product="washing_machine")
    c["fault_category"], c["symptom_text"] = g.rng.choice(CONTRADICTIONS)
    return c, "escalate"


def near_threshold_repair(g):
    return g.base("in_warranty", (0.585, 0.599)), "repair"


SCENARIOS: Dict[str, Scenario] = {f.__name__: f for f in [
    oow_repair, oow_replace_cost, oow_replace_age, iw_repair, iw_replace_cost, iw_replace_lead,
    d3_replace, d3_not_applicable, unknown_young, unknown_old, esc_repeat_negative,
    esc_null_part_price, esc_null_labour, esc_null_replacement, replace_null_replacement_long_lead,
    esc_hazard, negated_hazard_repair, esc_contradiction, near_threshold_repair,
]}


def generate(seed: int = DEFAULT_SEED, per_scenario: int = DEFAULT_PER_SCENARIO) -> List[Dict[str, Any]]:
    g = Gen(random.Random(seed))
    rows = []
    for name, scenario in SCENARIOS.items():
        for i in range(per_scenario):
            case, decision = scenario(g)
            # D5a must not fire accidentally outside its own scenario.
            if name != "esc_repeat_negative" and case["prior_repairs_12m"] >= 2:
                case["prior_repairs_12m"] = 0
            case["case_id"] = f"SYN-{name}-{i:03d}"
            cost = expected_cost(case)
            rows.append({"scenario": name, "case": g.noisy(case),
                         "expected": {"decision": decision, "estimated_repair_cost": cost}})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--per-scenario", type=int, default=DEFAULT_PER_SCENARIO)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "synthetic_cases.jsonl"))
    args = ap.parse_args()
    rows = generate(args.seed, args.per_scenario)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} cases ({len(SCENARIOS)} scenarios x {args.per_scenario}) to {out}")


if __name__ == "__main__":
    main()
