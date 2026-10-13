# Testing

This document covers the tests from a tester's point of view: the plan, what each requirement is covered by, a catalogue of representative test cases with their real results, the defects found and fixed, and the latest run.

**Nothing in the result columns is typed by hand.** The traceability matrix, the catalogue's *Actual*/*Status* columns and the *Latest run* section are regenerated from a real pytest run:

```sh
.venv/bin/python scripts/test_report.py      # runs pytest, then rewrites the generated sections below
```

The script fails if any test fails, or if a catalogue row points at a test that no longer exists. `--with-e2e` also runs the browser tests and regenerates §5b. CI (`.github/workflows/ci.yml`) runs everything on every push.

## 1. Test plan

| | |
|---|---|
| **Item under test** | The repair/replace decision service: `POST /decide`, `GET /health`, the page at `/`, and the start command `./run.sh` |
| **Basis** | The assignment brief (§3 API contract, §4 rules, Appendices D–F) and the interpretations recorded in NOTES.md |
| **In scope** | API contract; rules D0–D6 and their precedence; input validation and tolerance; text heuristics (hazards, negation, contradictions); missing-field behaviour; determinism; latency; offline operation; fresh-clone start-up; UI smoke and layout |
| **Out of scope** | Accuracy on real appliance tickets (no real data available); load/soak testing beyond a latency bound; security penetration testing; mobile-device browsers (responsive widths are tested in desktop engines, not on physical phones); automated screen-reader runs (screen readers are covered by automated accessibility checks plus a manual VoiceOver + Chrome run, §3b; NVDA, JAWS, Safari and mobile readers were not tested) |
| **Levels** | Unit (cost, rules, text) → integration (HTTP via FastAPI `TestClient`, in-process) → system (fresh clone + `./run.sh` / `run.ps1` + real HTTP, in CI) → end-to-end UI in real browsers (`e2e/`, Playwright) → data-driven acceptance (synthetic corpus, hand-labelled fixtures, challenge set) |
| **Techniques** | Equivalence partitioning; boundary-value analysis at every threshold (just below / at / just above); decision tables for warranty × rule × missing input; precedence tests; negative and invalid-input testing; false-friend tests for text ("shock absorber", "fireplace", "current bill"); exploratory testing turned into regression tests; oracle tests against the brief's three examples |
| **Oracles** | The brief's worked examples and rule text; labels fixed *before* running the engine for hand-labelled and challenge cases; scenario-by-construction labels for the synthetic corpus (not produced by the engine) |
| **Environment** | CI: Linux, macOS and Windows × Python 3.9, 3.12, 3.13, 3.14 for the suite; fresh-clone start (`scripts/smoke_start.py`: `run.sh` on Linux/macOS, `run.ps1` on Windows; /health within 60 s) on all three OSes with Python 3.9 and 3.14; browser tests in Chromium, Firefox and WebKit on all three OSes. Local: macOS, Python 3.13 and 3.11. Pinned dependencies (`requirements.txt`, `requirements-e2e.txt`). Sockets and DNS are patched to raise during the unit suite, so the run proves offline operation; the browser tests fail if the page requests anything not served by the local server |
| **Entry criteria** | Dependencies install from `requirements.txt`; the service starts and `/health` returns ok |
| **Exit criteria** | 100% of automated tests pass; every requirement in §2 has at least one passing test; the three brief examples match; fresh-clone start-up passes in CI; no open defects of severity High |
| **Risks** | Hidden test data uses wording and formats we have not seen; the brief is ambiguous on several points (NOTES.md). Both are mitigated by tolerant input handling and documented interpretations, not eliminated |

## 2. Requirements traceability

Every requirement maps to the automated tests that cover it (matched by test name) and to representative catalogue cases in §3.

<!-- GENERATED:TRACEABILITY:START -->
| Req | Requirement | Source | Automated tests | Passed | Catalogue cases |
|---|---|---|---|---|---|
| R01 | POST /decide accepts one JSON case and returns JSON | Brief §3 | 7 | ✅ 7/7 | — |
| R02 | Response has exactly case_id, decision, estimated_repair_cost, confidence, reason | Brief §3 | 13 | ✅ 13/13 | TC-004 |
| R03 | case_id is echoed unchanged | Brief §3 | 4 | ✅ 4/4 | TC-005, TC-006 |
| R04 | decision is one of repair / replace / escalate | Brief §3 | 9 | ✅ 9/9 | — |
| R05 | confidence is a number in [0, 1] | Brief §3 | 13 | ✅ 13/13 | — |
| R06 | reason is one sentence naming the deciding rule | Brief §3 | 4 | ✅ 4/4 | TC-013 |
| R07 | GET /health returns 200 {"status": "ok"} | Brief §4 | 1 | ✅ 1/1 | TC-001, TC-143 |
| R08 | Single page served at / by the same process; no remote assets | Brief §4–5 | 2 | ✅ 2/2 | TC-002, TC-003 |
| R09 | Works with the network off; tests run offline | Brief §4–5 | 308 | ✅ 308/308 | — |
| R10 | Each request answered in under 1 second | Brief §4 | 1 | ✅ 1/1 | TC-007 |
| R11 | D0 repair-cost formula; null only when it cannot be computed | Appendix D0 | 15 | ✅ 15/15 | TC-020, TC-021, TC-022, TC-023, TC-024, TC-025, TC-026 |
| R12 | D1a in/extended warranty: replace if cost > 60% of replacement | Appendix D1 | 8 | ✅ 8/8 | TC-030, TC-031, TC-032 |
| R13 | D1b replace if any required part lead time > 21 days | Appendix D1 | 6 | ✅ 6/6 | TC-033, TC-034, TC-035, TC-036 |
| R14 | D2 out of warranty: repair iff cost <= 50% and age <= 70% of life | Appendix D2, E | 11 | ✅ 11/11 | TC-040, TC-041, TC-042, TC-043 |
| R15 | D3 travel > 120 min and cost > 40% -> replace, any warranty | Appendix D3 | 11 | ✅ 11/11 | TC-050, TC-051, TC-052, TC-053, TC-054 |
| R16 | D4 unknown warranty mapped by age (> 24 months), lower confidence | Appendix D4 | 6 | ✅ 6/6 | TC-060, TC-061, TC-062, TC-063 |
| R17 | D5 escalate: >= 2 repairs and negative sentiment | Appendix D5 | 7 | ✅ 7/7 | TC-070, TC-071, TC-072 |
| R18 | D5 escalate: null part price or labour hours | Appendix D5 | 3 | ✅ 3/3 | TC-073, TC-074 |
| R19 | D5 escalate: replacement price null and the decision depends on it | Appendix D5 | 7 | ✅ 7/7 | TC-075, TC-076, TC-077 |
| R20 | D5 escalate: safety hazard in symptom text (negation-aware) | Appendix D5 | 77 | ✅ 77/77 | TC-078, TC-079, TC-080, TC-081, TC-082, TC-083, TC-084, TC-085, TC-086, TC-087, TC-088, TC-089 |
| R21 | D5 escalate: symptom text contradicts structured fields | Appendix D5 | 31 | ✅ 31/31 | TC-090, TC-091, TC-092, TC-093, TC-094 |
| R22 | D6 precedence: D5 > D3 > D1/D2 | Appendix D6 | 7 | ✅ 7/7 | TC-100, TC-101, TC-102 |
| R23 | D6 within 2 percentage points: decide by rule, lower confidence | Appendix D6 | 9 | ✅ 9/9 | TC-103, TC-104 |
| R24 | Invalid input rejected cleanly (422), never a 500 | Design (NOTES 9) | 24 | ✅ 24/24 | TC-110, TC-111, TC-112, TC-113, TC-114, TC-118 |
| R25 | Tolerant of format: enum spelling, synonyms, abbreviations, numeric strings | Design (NOTES 9) | 12 | ✅ 12/12 | TC-115, TC-116, TC-117 |
| R26 | Missing fields never crash; escalate only when the answer depends on them | Brief §3, NOTES 3 | 13 | ✅ 13/13 | TC-119 |
| R27 | The three worked examples match the brief | Brief §3 | 6 | ✅ 6/6 | TC-010, TC-011, TC-012 |
| R28 | Deterministic: identical input gives identical output | Design | 3 | ✅ 3/3 | TC-008 |
| R29 | Does not escalate everything | Brief §3 (metric) | 10 | ✅ 10/10 | TC-120, TC-130 |
| R30 | Behaviour on unseen styles of data (challenge set) | Brief §4 ('will not look like yours') | 14 | ✅ 14/14 | TC-131, TC-132, TC-133 |
| R31 | Starts from a fresh clone with one command; /health ready within a bounded time; Python 3.9-3.14 | Brief §4 ('runs from a fresh clone') | 11 | ✅ 11/11 | TC-140, TC-141, TC-142, TC-144 |
<!-- GENERATED:TRACEABILITY:END -->

## 3. Test-case catalogue

A selection of representative cases. The full suite has more, mostly parametrised variants. *Technique* is the design technique the case comes from. Each row maps to exactly one automated test, listed in `scripts/test_report.py`.

<!-- GENERATED:CATALOGUE:START -->
| ID | Req | Technique | Test case | Input | Expected | Actual | Status |
|---|---|---|---|---|---|---|---|
| TC-001 | R07 | Smoke | Health check | GET /health | 200, {"status":"ok"} | as expected | ✅ pass |
| TC-002 | R08 | Smoke | UI served at / | GET /, /static/app.js, /static/app.css | 200, HTML page with the case form | as expected | ✅ pass |
| TC-003 | R08 | Static check | No remote assets in the UI | all files in app/static | no http(s) src/href, @import or remote fetch | as expected | ✅ pass |
| TC-004 | R02 | Contract | Exact response fields | valid case | keys = the 5 contract fields; reason ends with '.' | as expected | ✅ pass |
| TC-005 | R03 | Equivalence | case_id echo: unicode | case_id 'ünïcode-✓' | same value returned | as expected | ✅ pass |
| TC-006 | R03 | Equivalence | case_id echo: integer | case_id 12345 | 12345 returned as a number | as expected | ✅ pass |
| TC-007 | R10 | Performance | Latency under load-ish input | 200 parts, long text, 20 requests | < 0.25 s per request | as expected | ✅ pass |
| TC-008 | R28 | Repeatability | Deterministic over HTTP | same case x20 | one distinct response | as expected | ✅ pass |
| TC-010 | R27 | Oracle (brief) | Example C-2001 | examples/C-2001.request.json | repair, 8150.0, 0.9 | as expected | ✅ pass |
| TC-011 | R27 | Oracle (brief) | Example C-2002 | examples/C-2002.request.json | replace, 16675.0, 0.85 | as expected | ✅ pass |
| TC-012 | R27 | Oracle (brief) | Example C-2003 | examples/C-2003.request.json | escalate, null, 0.7 | as expected | ✅ pass |
| TC-013 | R06 | Oracle (brief) | C-2001 reason text | C-2001 | identical to the brief's reason (rule D2) | as expected | ✅ pass |
| TC-020 | R11 | Oracle (brief) | D0 formula, example 1 | 6200 + 1.5h x 900 + 40 min | 8150.0 | as expected | ✅ pass |
| TC-021 | R11 | Spec ambiguity | Travel not doubled | 60 min travel at 900/h, no parts/labour | 900.0 (not 1800) | as expected | ✅ pass |
| TC-022 | R11 | Equivalence | Duplicate SKUs summed | A 100, A 100, B 50.5 | 250.5 | as expected | ✅ pass |
| TC-023 | R11 | Boundary | Zero vs null | no parts, 0 labour, 0 travel | 0.0 (computable, not null) | as expected | ✅ pass |
| TC-024 | R11 | Negative | Null part price | part price null | cost null; SKU named | as expected | ✅ pass |
| TC-025 | R11 | Negative | Null travel | travel null | cost computed without travel | as expected | ✅ pass |
| TC-026 | R11 | Precision | No float drift | prices 0.1 + 0.2 | exactly 3/10 | as expected | ✅ pass |
| TC-030 | R12 | Boundary | D1a exactly 60% | in_warranty, cost 6000 / 10000 | repair (60% is not 'exceeds') | as expected | ✅ pass |
| TC-031 | R12 | Boundary | D1a just over 60% | in_warranty, cost 6001 / 10000 | replace | as expected | ✅ pass |
| TC-032 | R12 | Equivalence | D1a for extended warranty | extended, 60.01% | replace | as expected | ✅ pass |
| TC-033 | R13 | Boundary | D1b lead time 21 days | in_warranty, lead 21 | repair (D1a) | as expected | ✅ pass |
| TC-034 | R13 | Boundary | D1b lead time 22 days | in_warranty, lead 22 | replace (D1b) | as expected | ✅ pass |
| TC-035 | R13 | Decision table | D1b not applied out of warranty | out_of_warranty, lead 60 | repair | as expected | ✅ pass |
| TC-036 | R13 | Negative | Null lead time | in_warranty, lead null, 10% | repair, lower confidence | as expected | ✅ pass |
| TC-040 | R14 | Boundary | D2 exactly 50% | out_of_warranty, 50.00% | repair | as expected | ✅ pass |
| TC-041 | R14 | Boundary | D2 just over 50% | out_of_warranty, 50.01% | replace | as expected | ✅ pass |
| TC-042 | R14 | Boundary | D2 age at 70% of life (washer) | 84 months vs 85 months | repair at 84, replace at 85 | as expected | ✅ pass |
| TC-043 | R14 | Boundary | D2 non-integer age limit (dishwasher) | 75 vs 76 months (limit 75.6) | repair, then replace | as expected | ✅ pass |
| TC-050 | R15 | Boundary | D3 travel 120 min | 120 min, 45% | D3 not applied (D1a) | as expected | ✅ pass |
| TC-051 | R15 | Boundary | D3 cost exactly 40% | 121 min, 40.00% | D3 not applied (D1a) | as expected | ✅ pass |
| TC-052 | R15 | Boundary | D3 fires | 121 min, 40.01% | replace (D3) | as expected | ✅ pass |
| TC-053 | R15 | Decision table | D3 regardless of warranty | unknown warranty, 121 min, 45% | replace (D3) | as expected | ✅ pass |
| TC-054 | R15 | Negative | Null travel does not fire D3 | travel null, 45% | repair (D1a), lower confidence | as expected | ✅ pass |
| TC-060 | R16 | Boundary | D4 age 24 months | unknown, 24 months, 55% | in-warranty reading: repair (D1a) | as expected | ✅ pass |
| TC-061 | R16 | Boundary | D4 age 25 months | unknown, 25 months, 55% | out-of-warranty reading: replace (D2) | as expected | ✅ pass |
| TC-062 | R16 | Negative | D4 with no age, readings disagree | unknown, age null, 10% | escalate | as expected | ✅ pass |
| TC-063 | R16 | Negative | D4 with no age, readings agree | unknown, age null, 70% | replace | as expected | ✅ pass |
| TC-070 | R17 | Boundary | D5a two repairs + negative | prior 2, negative | escalate | as expected | ✅ pass |
| TC-071 | R17 | Boundary | D5a one repair + negative | prior 1, negative | repair | as expected | ✅ pass |
| TC-072 | R17 | Decision table | D5a two repairs + neutral | prior 2, neutral | repair | as expected | ✅ pass |
| TC-073 | R18 | Negative | D5b null labour hours | labour_hours null | escalate, cost null | as expected | ✅ pass |
| TC-074 | R18 | Precedence | D5b beats D1b | part price null, lead 40 | escalate | as expected | ✅ pass |
| TC-075 | R19 | Negative | Replacement null, ratio decides | in_warranty, replacement null | escalate; cost still reported | as expected | ✅ pass |
| TC-076 | R19 | Decision table | Replacement null, D1b decides | replacement null, lead 30 | replace (D1b) | as expected | ✅ pass |
| TC-077 | R19 | Decision table | Replacement null, age decides | replacement null, age 110 months | replace (D2) | as expected | ✅ pass |
| TC-078 | R20 | Equivalence | Hazard: sparks | 'sparks from outlet' | sparks detected | as expected | ✅ pass |
| TC-079 | R20 | Equivalence | Hazard: gas smell variant | 'smells of gas near the hob' | gas smell detected | as expected | ✅ pass |
| TC-080 | R20 | Regression (DEF-02) | Hazard: verb + words + shock | 'the casing gave my son a shock' | electric shock detected | as expected | ✅ pass |
| TC-081 | R20 | Negative | Negated hazard list | 'No sparks, smoke or burning smell.' | no hazard | as expected | ✅ pass |
| TC-082 | R20 | Negative | False friend: shock absorber | 'shock absorbers worn, loud banging' | no hazard | as expected | ✅ pass |
| TC-083 | R20 | Negative | False friend: fireplace | 'fireplace model next to the unit' | no hazard | as expected | ✅ pass |
| TC-084 | R20 | Scope | Negation does not cross clauses | 'not cooling, sparks from plug' | sparks detected | as expected | ✅ pass |
| TC-085 | R20 | Regression (DEF-04) | Misspelt hazard | 'sparkes from the plug point' | sparks detected | as expected | ✅ pass |
| TC-086 | R20 | Regression (DEF-05) | Hinglish shock | 'body mein current lag raha hai' | electric shock detected | as expected | ✅ pass |
| TC-087 | R20 | Regression (DEF-07) | Hinglish negation | 'koi dhuan nahi, chingari bhi nahi' | no hazard | as expected | ✅ pass |
| TC-088 | R20 | Negative | False friend: 'current bill' | 'current bill is very high' | no hazard | as expected | ✅ pass |
| TC-089 | R20 | System | Hazard escalates, cost kept | 'smoke coming from the back…' | escalate, cost 8150.0 | as expected | ✅ pass |
| TC-090 | R21 | Oracle (brief) | Brief contradiction example | not_cooling + 'door will not close' | escalate, confidence 0.60 | as expected | ✅ pass |
| TC-091 | R21 | Negative | Related symptoms not contradictory | 'door will not close so the fridge is warm' | no contradiction | as expected | ✅ pass |
| TC-092 | R21 | Negative | Unfamiliar wording | 'customer unhappy, please call back' | no contradiction | as expected | ✅ pass |
| TC-093 | R21 | Equivalence | Text names another appliance | washing_machine + 'dishwasher will not drain' | product contradiction | as expected | ✅ pass |
| TC-094 | R21 | Equivalence | Warranty stated in text | in_warranty + 'warranty expired' | warranty contradiction | as expected | ✅ pass |
| TC-100 | R22 | Precedence | Escalation beats D3 | D3 conditions + D5a | escalate | as expected | ✅ pass |
| TC-101 | R22 | Precedence | Escalation beats D1b | lead 40 + 'sparks from the plug' | escalate | as expected | ✅ pass |
| TC-102 | R22 | Precedence | D3 beats D1 repair | in_warranty 50%, travel 200 | replace (D3) | as expected | ✅ pass |
| TC-103 | R23 | Boundary | Near threshold (absolute pp) | 58.5% and 62.1% vs 60% | near flagged at 58.5% only | as expected | ✅ pass |
| TC-104 | R23 | Boundary | Near threshold lowers confidence | in_warranty 59% | repair, confidence < 0.90 | as expected | ✅ pass |
| TC-110 | R24 | Negative | Unknown enum | product_category 'toaster' | 422 with field location | as expected | ✅ pass |
| TC-111 | R24 | Negative | Negative price | replacement_price -1 | 422 | as expected | ✅ pass |
| TC-112 | R24 | Regression (DEF-01) | NaN input | raw JSON with NaN | 422 (was 500) | as expected | ✅ pass |
| TC-113 | R24 | Negative | Malformed JSON | '{not json' | 422 | as expected | ✅ pass |
| TC-114 | R24 | Negative | Missing case_id | body without case_id | 422 | as expected | ✅ pass |
| TC-115 | R25 | Format | Enum spelling variants | 'Washing Machine', 'Out-of-Warranty' | normalised; repair | as expected | ✅ pass |
| TC-116 | R25 | Format | Numbers as strings | '36,000', 'Rs 900' | accepted; cost 8150.0 | as expected | ✅ pass |
| TC-117 | R25 | Regression (DEF-06) | Warranty abbreviation | warranty 'OOW' | out_of_warranty (was 422) | as expected | ✅ pass |
| TC-118 | R24 | Negative | Unknown abbreviation stays invalid | warranty 'OOWX' | 422 | as expected | ✅ pass |
| TC-119 | R26 | Robustness | Only case_id present | {"case_id": "MIN"} | 200, escalate, cost null | as expected | ✅ pass |
| TC-120 | R29 | Guard | Normal cases not escalated | 8 plain cases across ratios | no escalate | as expected | ✅ pass |
| TC-130 | R29 | Data-driven | Synthetic corpus (seed 2026) | 570 cases, 19 scenarios | 0 misses; macro-F1 1.0 | as expected | ✅ pass |
| TC-131 | R30 | Data-driven | Hand-labelled adversarial set | 35 cases | 0 misses | as expected | ✅ pass |
| TC-132 | R30 | Exploratory -> regression | Challenge: Hinglish shock | 'body mein current lag raha hai' | escalate | as expected | ✅ pass |
| TC-133 | R30 | Exploratory -> regression | Challenge: OOW | warranty 'OOW' | repair | as expected | ✅ pass |
| TC-140 | R31 | System | Real server start passes the grader check | uvicorn child process + smoke check | healthy, / served, 3 examples match | as expected | ✅ pass |
| TC-141 | R31 | Negative (DEF-16) | Launcher crash fails fast | launcher exits with code 3 | fails in < 20 s with exit code and output | as expected | ✅ pass |
| TC-142 | R31 | Negative (DEF-17) | No listener: bounded wait | launcher never binds, 3 s deadline | fails in < 20 s with process and port diagnostics | as expected | ✅ pass |
| TC-143 | R07 | Contract | Health body must be exact | {"status":"starting"} | not ready | as expected | ✅ pass |
| TC-144 | R31 | Regression (DEF-15) | Pins have Python 3.14 wheels | requirements.txt | pydantic >= 2.12 | as expected | ✅ pass |
<!-- GENERATED:CATALOGUE:END -->

### 3a. UI checks

The UI is not scored by the brief, but it is tested. The checks below are now **automated in `e2e/test_ui.py`** and run in Chromium, Firefox and WebKit (Safari's engine) on Linux, macOS and Windows in CI. Per-browser results are in §5b. The table records what each check covers.

| ID | Check | Expected | Result |
|---|---|---|---|
| UI-01 | Load C-2001 / C-2002 / C-2003 and get a recommendation | Repair 8,150.00 / Replace 16,675.00 / Escalate, "Cannot compute" | Pass |
| UI-02 | Client-side validation: labour hours −3, no case ID | Error summary lists both; fields marked invalid | Pass |
| UI-03 | Part added with a blank price | Escalate; reason names the missing part price | Pass |
| UI-04 | Edit an input after a decision | "Inputs changed" banner appears; Ctrl+Enter re-runs and clears it | Pass |
| UI-05 | Status pill | Shows "Policy engine online" from the real `/health` | Pass |
| UI-06 | 390, 820 and 1440 px viewports | No horizontal page scroll (`scrollWidth == clientWidth`) | Pass at all three |
| UI-07 | Keyboard only, real key events via Chrome DevTools | Tab order follows the visual order (skip links → samples → fields top to bottom → submit); every focused control shows a visible focus ring; Enter on a sample loads it; Ctrl+Enter decides and moves focus to the Recommendation heading; Tab reaches "All policy checks" and Enter opens it | Pass (22 controls, none without a visible ring) |
| UI-08 | Colour contrast of every text/background token pair (WCAG formula) | Text ≥ 4.5:1; focus ring and input borders ≥ 3:1 | Pass after DEF-09 fix (lowest text pair 5.19:1; borders 3.06:1) |
| UI-09 | Cost breakdown for C-2001 | Parts 6,200 + labour 1.5 h × 900 = 1,350 + travel 40 min ÷ 60 × 900 = 600 = 8,150 | Pass; also asserted in `test_cost_formula_exposes_every_component` |
| UI-10 | axe-core audit (WCAG 2.x rules) in four states: empty, repair, escalate, validation errors | Zero violations | Automated: `test_axe_finds_no_violations` (after DEF-12 fix) |
| UI-11 | Accessible names and roles (what a screen reader announces) | Every field announced with its label; required state announced; headings at levels 1 and 2; status messages in live regions; decision-path state given in words, not only colour or icon; comparison bar has a text alternative | Automated: `test_screen_reader_names_and_roles` |
| UI-12 | Text zoom to 200% (WCAG 1.4.4) | No horizontal scroll at 1280 px | Automated: `test_200_percent_text_zoom_still_fits` |
| UI-13 | No external requests | Every request goes to the local server | Automated: checked on every browser test by the `page` fixture |

### 3b. Screen readers (manual)

Automated checks (UI-10, UI-11) cover the information a screen reader reads from the page: names, roles, states and live regions. They cannot prove what a particular screen reader actually *says*, and driving VoiceOver or NVDA cannot be automated reliably, so this check is run by hand.

**Manual run: 13 October 2026, by the author.**
- **Reader and browser:** VoiceOver on macOS, Google Chrome, against the local server.
- **Versions:** the report did not include them. This machine had macOS 26.5.1 and Chrome 151.0.7922.138 when the result was recorded.
- **Result:** 6/6 passed. The observations below are as reported.

| ID | Steps | Expected | Result | Observation (as reported) |
|---|---|---|---|---|
| SR-01 | Open `/`, press Tab twice from the top | "Skip to case intake, link", then "Skip to recommendation, link" | Pass | Both skip links are announced during keyboard navigation and can be activated. |
| SR-02 | Tab to the Case ID field | "Case ID, required, edit text" (wording varies by reader) | Pass | VoiceOver announces the Case ID label, required status, and editable text field. |
| SR-03 | Leave Case ID blank and press Ctrl+Enter | Error summary read out ("Check these fields before continuing…"), focus on it | Pass | Submitting an empty Case ID announces the validation error. Focus moves to the appropriate error or input location. |
| SR-04 | Load sample C-2001, press Ctrl+Enter | Status "Recommendation ready for C-2001: repair." announced; focus on the "Recommendation" heading | Pass | Loading case C-2001 announces the recommendation-ready status, and the Recommendation heading can be reached using keyboard navigation. |
| SR-05 | Read the result with the reading keys (VO+Right / Down arrow) | Action, rule, reason, cost and comparison, decision-path states in words | Pass | The action, rule, reason, estimated cost, and path information are understandable when navigating the result. |
| SR-06 | Open "All policy checks" with Enter | Each check read with "not triggered", "triggered" or "could not be evaluated" | Pass | Each policy check and its associated state are announced in a comprehensible order. |

Additional observations reported: none.

**Where automation pins down what the manual notes leave open.** The SR-03 and SR-04 notes are less specific than the expected results about *where* focus lands. The browser suite checks that exactly, in all three engines:
- After a failed submit, focus is on the error summary (`test_client_side_validation`).
- After a decision, focus moves to the Recommendation heading (`test_keyboard_only_decision`).

**Not covered:**
- NVDA or JAWS on Windows.
- VoiceOver with Safari, which can differ from VoiceOver with Chrome.
- iOS or Android screen readers.

## 4. Defect log

Each defect found during development, how it was found, and the regression test that now guards it.

| ID | Severity | Found by | Symptom | Root cause | Fix | Regression test |
|---|---|---|---|---|---|---|
| DEF-01 | High | Automated test (`test_nan_and_infinity_rejected`) | A `NaN` or `Infinity` input returned **HTTP 500** instead of 422 | FastAPI's default 422 handler echoes the input back; `NaN` cannot be serialised to JSON | Custom validation handler returns only location and message | TC-112 |
| DEF-02 | High | Synthetic corpus (3 of 40 hazard cases missed) | "the casing gave my son a shock" was not escalated | Shock pattern required the verb right next to "shock" | Allow up to three words in between, still excluding "shock absorber" | TC-080, TC-130 |
| DEF-03 | Low | Manual UI check at 390 px | Page scrolled sideways on phones | Default `fieldset { min-width: min-content }`, plus a screen-reader-only span escaping its scroll container | `min-width: 0`; `position: relative` on the table wrapper | UI-06 (manual) |
| DEF-04 | High | Exploratory challenge (14 cases) | "sparkes from the plug point" was not escalated | Misspellings not recognised | Explicit whole-word misspelling list | TC-085 |
| DEF-05 | High | Exploratory challenge | "body mein current lag raha hai" (Hinglish for getting a shock) was not escalated | No Hinglish vocabulary | Short documented Hinglish phrase list | TC-086, TC-132 |
| DEF-06 | Medium | Exploratory challenge | Warranty `"OOW"` returned **HTTP 422** | Abbreviation not in the alias table | `OOW` / `IW` / `EW` aliases; other abbreviations stay invalid | TC-117, TC-118, TC-133 |
| DEF-07 | Medium | Manual probe while fixing DEF-05 | "koi dhuan nahi, chingari bhi nahi" ("no smoke, no sparks either") was flagged as a hazard | Negation check returned early and never ran the post-negation check | Post-negation checked first; allow "bhi" | TC-087 |
| DEF-09 | Medium | Contrast check during the UI polish | Input borders were 1.62:1 against white, below the 3:1 WCAG 1.4.11 minimum for control boundaries | Light border token `#c4ccd8` | Border token `#8a94a6` (3.06:1) | UI-08 (manual) |
| DEF-10 | Low | Code reading during the UI polish | The display-helper block in `app/policy.py` existed twice (identical copies) | An edit replaced a section marker that appeared twice in the file | Duplicate removed; marker renamed so it is unique | Full suite (294 tests) |
| DEF-11 | High | Browser tests (WebKit) | In Safari's engine, dropdowns showed no focus indicator | WebKit does not apply `:focus-visible` to `<select>` and drops `box-shadow` on native dropdowns | Fields use `:focus` with an `outline` ring | `test_every_focused_control_shows_a_focus_indicator[webkit]` |
| DEF-12 | Medium | axe-core audit, all engines | Raw-response `<pre>` scrolled sideways but could not be reached by keyboard (`scrollable-region-focusable`, serious) | Scrollable element without `tabindex` | `tabindex="0"`, `role="region"` and a label | `test_axe_finds_no_violations` |
| DEF-13 | High | Code review before adding Windows to CI | Test suite would crash on Windows: page files read without an encoding (cp1252 cannot decode "—", "÷") | `Path.read_text()` uses the locale encoding | Every read and write states UTF-8 | Windows CI job; suite run with `LC_ALL=C` locally |
| DEF-14 | Medium | Contrast review of my own fix for DEF-11 | The first replacement focus ring was semi-transparent, about 2:1 against white, below 3:1 | `rgba(..., 0.45)` outline | Solid `var(--focus)` outline, 6.27:1 | UI-08 |
| DEF-15 | **Critical** | Windows CI diagnostic run | `run.ps1` exited with code 1: `Failed building wheel for pydantic-core`. Any machine whose default Python is **3.14** (on any OS) could not install the service | `pydantic==2.10.4` needs `pydantic-core 2.27.x`, which has no Python 3.14 wheel, so pip tried to compile Rust. CI never tested 3.14. On Windows, `py` picked 3.14 | Pins raised to fastapi 0.128.8 / pydantic 2.13.5 (pydantic-core 2.46.5 has cp39–cp314 wheels) / uvicorn 0.39.0 / pytest 8.4.2. `run.ps1` prefers PATH `python` over `py`. Python 3.14 added to CI | TC-144; fresh-start CI on Python 3.9 and 3.14 × 3 OSes |
| DEF-16 | High | Windows CI diagnostic run (control process) | Windows fresh-start job never became healthy; `server.log`/`server.err` were 0 bytes | GitHub's Windows runners kill every process a step started when the step ends. The server, started in its own 5 s step, was killed while still creating `.venv` (a control `Start-Sleep 900` died too) | `scripts/smoke_start.py` starts the launcher and checks it in one process, so they share a lifetime on every OS | TC-140, TC-141 |
| DEF-17 | Medium | Windows CI timing | A "240 s" health wait took about 12.5 minutes | Each `curl` to a refused port takes about 2 s on Windows, with no per-request timeout, and `localhost` tried IPv6 first | 2 s per-request timeout, 60 s overall deadline, `127.0.0.1`, diagnostics on failure (process alive, port listening, last error, log tail) | TC-142 |
| DEF-18 | High | Windows CI | Every Windows unit-test run failed: `'ProactorEventLoop' object has no attribute '_ssock'` | The test network guard blocked all `connect` calls, but Windows' event loop builds its internal socketpair by connecting to 127.0.0.1 | Guard allows loopback only; external hosts and DNS still raise | `test_network_guard_blocks_external_hosts_but_allows_loopback` |
| DEF-19 | Low | Windows CI | Browser report crashed after 66/66 tests passed: `UnicodeEncodeError` on "✅" | Windows console uses cp1252 | Report reconfigures stdout/stderr to UTF-8 | Windows browser job |
| DEF-20 | Medium | CI latency test on slower runners (0.26–0.28 s vs the 0.25 s bound) | The worst-case request (200 parts, 14,600-character text) took about 122 ms locally | `_is_negated` re-tokenised the whole text for every hazard mention, so it was O(n²) | Scan a bounded window (400 chars, cut word dropped); now 26 ms locally, linear in text length. The 0.25 s bound was kept, not loosened | `test_hazard_detection_scales_linearly`, `test_negation_window_does_not_read_a_cut_word_as_negation`, `test_latency_well_under_one_second` |
| DEF-08 | Medium | Code review, before the first test run | Contraction rule would have rewritten "element" as "eleme not" | Regex `n'?t` made the apostrophe optional | Require the apostrophe | `test_normalise_contractions` |

Open defects: none known. Known limitations, which are not defects, are listed in NOTES.md and DATA.md.

## 5. Latest run (unit and integration suite)

<!-- GENERATED:LATEST-RUN:START -->
- **Run at:** 2026-10-13 10:31 UTC
- **Environment:** Python 3.13.7 on Darwin arm64; FastAPI 0.128.8, Pydantic 2.13.5; network blocked by `tests/conftest.py`
- **Result:** ✅ PASS: 308 passed, 0 failed, 0 skipped, 308 total, 5.5 s

| Test file | Tests | Passed | Failed | Time (s) |
|---|---|---|---|---|
| `tests/test_api.py` | 68 | 68 | 0 | 0.61 |
| `tests/test_challenge.py` | 14 | 14 | 0 | 0.01 |
| `tests/test_corpora.py` | 8 | 8 | 0 | 0.23 |
| `tests/test_cost.py` | 13 | 13 | 0 | 0.00 |
| `tests/test_escalation.py` | 24 | 24 | 0 | 0.03 |
| `tests/test_examples.py` | 6 | 6 | 0 | 0.01 |
| `tests/test_rules.py` | 60 | 60 | 0 | 0.03 |
| `tests/test_startup.py` | 11 | 11 | 0 | 4.50 |
| `tests/test_text.py` | 104 | 104 | 0 | 0.04 |

Metric self-checks on our own data (the brief's metrics; **not** evidence of hidden-set accuracy):

| Data set | Cases | Macro-F1 | Cost within 10% | Decision matches |
|---|---|---|---|---|
| Synthetic corpus (seed 2026) | 760 | 1.0 | 1.0 | 760/760 |
| Hand-labelled fixtures | 35 | 1.0 | 1.0 | 35/35 |
| Challenge set (decision only) | 14 | 1.0 | n/a | 14/14 |
<!-- GENERATED:LATEST-RUN:END -->

## 5b. Latest browser run (end-to-end)

<!-- GENERATED:E2E:START -->
- **Run at:** 2026-10-13 10:31 UTC on Darwin arm64, Playwright 1.55.0, axe-core via axe-playwright-python 0.1.8
- **Result:** ✅ PASS: chromium 22/22, firefox 22/22, webkit 22/22

| Browser test | Chromium | Firefox | WebKit |
|---|---|---|---|
| `test_200_percent_text_zoom_still_fits` | ✅ | ✅ | ✅ |
| `test_add_and_remove_part` | ✅ | ✅ | ✅ |
| `test_axe_finds_no_violations [empty]` | ✅ | ✅ | ✅ |
| `test_axe_finds_no_violations [errors]` | ✅ | ✅ | ✅ |
| `test_axe_finds_no_violations [escalate]` | ✅ | ✅ | ✅ |
| `test_axe_finds_no_violations [repair]` | ✅ | ✅ | ✅ |
| `test_brief_examples_render [C-2001]` | ✅ | ✅ | ✅ |
| `test_brief_examples_render [C-2002]` | ✅ | ✅ | ✅ |
| `test_brief_examples_render [C-2003]` | ✅ | ✅ | ✅ |
| `test_client_side_validation` | ✅ | ✅ | ✅ |
| `test_cost_formula_shows_every_component` | ✅ | ✅ | ✅ |
| `test_every_focused_control_shows_a_focus_indicator` | ✅ | ✅ | ✅ |
| `test_keyboard_only_decision` | ✅ | ✅ | ✅ |
| `test_no_horizontal_scroll [1024]` | ✅ | ✅ | ✅ |
| `test_no_horizontal_scroll [1440]` | ✅ | ✅ | ✅ |
| `test_no_horizontal_scroll [1920]` | ✅ | ✅ | ✅ |
| `test_no_horizontal_scroll [360]` | ✅ | ✅ | ✅ |
| `test_no_horizontal_scroll [390]` | ✅ | ✅ | ✅ |
| `test_no_horizontal_scroll [768]` | ✅ | ✅ | ✅ |
| `test_screen_reader_names_and_roles` | ✅ | ✅ | ✅ |
| `test_stale_banner_and_rerun` | ✅ | ✅ | ✅ |
| `test_tab_order_follows_visual_order` | ✅ | ✅ | ✅ |
<!-- GENERATED:E2E:END -->
