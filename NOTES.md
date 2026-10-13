# Notes

**Approach.** I used a deterministic rules engine, not a model. The brief supplies the policy, so a classifier trained on rule-generated labels could only add errors. Rules D0–D6 and their precedence come from the brief, not from research. No external API is called at runtime; text checks are offline regexes, not an LLM.

**Decisions on ambiguous points (all tested):**

1. **Travel** is not doubled. The text says "allows for the return", but the formula and both examples use `minutes/60 × rate` (C-2001: 40 min → 600).
2. **Null travel.** D0 says only a null part price or null labour hours makes the cost uncomputable. So null travel means a cost with no travel component, D3 does not fire, and confidence drops. It is not an escalation trigger.
3. **Missing data, one rule.** Override rules and triggers (D3, D1b, D5a) fire only on positive evidence; a missing input lowers confidence instead. Base rules (D1a, D2, D4 mapping) escalate only if some value of the missing input would change the answer. That is D5c's own "and the decision depends on it", applied consistently. Example: no replacement price, out of warranty, too old → still *replace*.
4. **D5b vs D5c.** D5b (null part price or labour) escalates unconditionally, as in example 3; D5c is conditional.
5. **Required parts.** There is no flag, so every listed part is required. Duplicate SKUs are summed.
6. **Inclusivity** is literal. "Exceeds"/"over" is `>`, "at most" is `≤`, so exactly 60% under D1a is repair. Arithmetic uses exact fractions.
7. **"Within 2 percentage points"** is absolute (\|ratio − threshold\| ≤ 0.02), for the 40/50/60/70% thresholds the decision actually evaluated. It is not applied to the day, minute or month thresholds.
8. **Confidence** is a heuristic, not a probability. Anchors are the brief's 0.90 / 0.85 / 0.70. Deductions: −0.10 unknown warranty, −0.10 near a threshold, −0.05 per non-decisive missing input. Contradiction-only escalations get 0.60; "missing input decides it" escalations get 0.65.
9. **Input.** Tolerant of format (enum case and spacing, synonyms, warranty abbreviations `OOW`/`IW`/`EW`, numeric strings, `labor_*`); strict on meaning (unknown enums, negatives, NaN/∞, wrong types → 422). Only `case_id` is required; missing warranty → `unknown`. `purchase_price` is used by no rule.
10. **Text.** Hazards use NegEx-style negation ("no sparks or smoke" → none; "not cooling, sparks at plug" → sparks). Contradictions need clear evidence: the text describes only incompatible fault families, names another appliance, or states another warranty status. Unfamiliar wording is never a contradiction. "Gas leak" on an AC or fridge is refrigerant; a gas *smell* is always a hazard. Before detection, an explicit whole-word list fixes common hazard misspellings ("sparkes", "smok") and a short phrase list maps documented Hinglish ("current lag raha hai", "dhuan", "chingari"); "nahi" counts as a negation.

**Found in testing.** The synthetic corpus caught a missed hazard phrasing ("gave my son a shock"). FastAPI's default 422 handler crashed on `NaN` input and returned a 500; a custom handler fixes it. A 14-case challenge in unseen styles scored 11/14 (missed "sparkes", "current lag raha hai", warranty `OOW`); after targeted fixes it is 14/14 and kept as a regression test.

**Cut.** ML and embeddings for text (no real labelled tickets; would cost explainability). Batch API, auth, persistence. Docker (not available to test, so not shipped untested). Broad multilingual support (only a small, documented Hinglish list).

**Limitations.** The keyword detectors will miss novel phrasing, misspellings not on the list, other languages and odd negation. "Might catch fire" deliberately counts as a hazard. The 100% synthetic scores measure agreement with my reading of the policy, not real-world accuracy.

**Next.** Real anonymised tickets to measure hazard recall and contradiction precision; confirm points 2, 3 and 7 with the policy owner; an explicit `required` flag on parts; calibrate confidence against reviewed outcomes.
