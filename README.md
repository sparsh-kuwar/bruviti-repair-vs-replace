# Repair vs Replace decision service

[![CI](https://github.com/sparsh-kuwar/bruviti-repair-vs-replace/actions/workflows/ci.yml/badge.svg)](https://github.com/sparsh-kuwar/bruviti-repair-vs-replace/actions/workflows/ci.yml)

Takes one appliance service case and returns **repair**, **replace** or **escalate**, with an estimated repair cost, a confidence and a one-sentence reason naming the rule that decided it. It applies the supplied policy (rules D0–D6) with a deterministic rules engine. There is no ML model, no LLM, and no network access at request time.

## Run it (one command)

Requirements: Python 3.9 or newer, and internet access the first time only (to install dependencies).

```sh
./run.sh
```

This creates `.venv/`, installs the pinned dependencies from `requirements.txt`, and starts the API and the UI in one process on **http://localhost:8000**. Running it again reuses the virtualenv. If the `python3` on your PATH is older than 3.9, run `PYTHON=/path/to/python3.11 ./run.sh`.

The equivalent manual steps:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Once the service is ready:

| Endpoint | What it does |
|---|---|
| `GET /health` | `200 {"status": "ok"}` |
| `POST /decide` | one case in, one decision out (contract below) |
| `POST /decide?explain=true` | same, plus a `trace`: every check the engine ran, the D5 escalation checks, and the precedence stages showing where the case stopped (the UI uses this) |
| `GET /` | single-page agent workspace: case intake on the left, recommendation on the right (decision, cost, confidence, decision path, policy checks, cost breakdown, copyable case note) |

## Run the tests

```sh
.venv/bin/python -m pytest -q
```

There are 292 tests. They run fully offline: `tests/conftest.py` disables sockets for the whole session, and FastAPI's `TestClient` calls the app in-process. They cover every rule and boundary, precedence, the three brief examples, text heuristics, validation, the HTTP contract, determinism and latency.

**[TESTING.md](TESTING.md)** presents them from a tester's point of view: the test plan, a requirements traceability matrix, an 84-case test catalogue, the defect log and the latest run. Its results are generated from a real run:

```sh
.venv/bin/python scripts/test_report.py
```

On every push, CI (GitHub Actions) runs the suite on Python 3.9 and 3.12, plus a fresh-clone job that starts the service with `./run.sh`, waits for `/health` and checks the three brief examples.

Score the engine with the brief's metrics (macro-F1, share of costs within 10%):

```sh
.venv/bin/python scripts/evaluate.py                                           # synthetic corpus, 760 cases
.venv/bin/python scripts/evaluate.py --file tests/fixtures/handwritten_cases.json
.venv/bin/python scripts/generate_cases.py                                     # write corpus to data/
```

## Example

```sh
curl -s localhost:8000/decide -H 'content-type: application/json' -d @examples/C-2001.request.json
```
```json
{"case_id":"C-2001","decision":"repair","estimated_repair_cost":8150.0,"confidence":0.9,
 "reason":"Out of warranty, repair cost 23% of replacement, age within 70% of expected life: rule D2."}
```

`examples/` holds the three reference cases from the brief, with the expected response for each.

## Contract summary

The request uses the brief's fields. Only `case_id` is required. Any other field may be omitted or `null`, and the engine decides whether the missing value matters (see NOTES.md).

| Input | Behaviour |
|---|---|
| Enum spelling such as `"Out of Warranty"`, `"Washing Machine"`, `"fridge"` | normalised |
| Numbers sent as strings, such as `"36,000"` or `"Rs 900"` | accepted |
| `labor_*` (US spelling) | accepted |
| Unknown enum values, negative or non-finite numbers, wrong JSON types, malformed JSON | rejected with **422** and a per-field message |

The response has exactly `case_id`, `decision`, `estimated_repair_cost` (`null` only when the cost cannot be computed), `confidence` (0–1) and `reason`.

## What's in this repo

How each deliverable the brief asks for maps to this repo:

| Brief asks for | Where |
|---|---|
| One command to install and run; how to run tests | This README: `./run.sh`, `pytest` |
| The service meeting the API contract | `app/` (`POST /decide`, `GET /health`) |
| A single page at `/` | `app/static/` (served by the same process) |
| `DATA.md`: data sourcing and test design | [DATA.md](DATA.md) |
| `NOTES.md`: decisions, cuts, next steps (one page) | [NOTES.md](NOTES.md) |
| `AI.md`: AI tools used and for what | [AI.md](AI.md) |
| `tests/` that run without network | `tests/` (292 tests) and [TESTING.md](TESTING.md) (plan, traceability, catalogue, defects, results) |

Extra material, not required by the brief:

| File | Purpose |
|---|---|
| [EXPLANATION.md](EXPLANATION.md) | Full walkthrough: architecture, every function, rules, interview Q&A |
| [research/RESEARCH_NOTES.md](research/RESEARCH_NOTES.md) | Design rationale with verified references |
| `examples/` | The three reference cases from the brief, with expected responses |
| `scripts/` | Synthetic data generator, metric evaluator, test-report generator |
| `.github/workflows/ci.yml` | CI: tests on Python 3.9 and 3.12, plus the fresh-clone start check |

## Layout

```
app/schemas.py   request/response models, normalisation and validation
app/cost.py      D0 cost formula (exact arithmetic)
app/text.py      offline safety-hazard and contradiction detection
app/policy.py    D1-D6 rules, precedence, confidence, reasons
app/main.py      FastAPI app: /decide, /health, / (static UI)
app/static/      the page (plain HTML/CSS/JS, no CDN)
scripts/         synthetic data generator, evaluator, test-report generator
tests/           pytest suite, hand-labelled and challenge fixtures
.github/         CI workflow
```

More detail: [NOTES.md](NOTES.md) (decisions, one page), [DATA.md](DATA.md) (data and test design), [EXPLANATION.md](EXPLANATION.md) (full walkthrough), [research/RESEARCH_NOTES.md](research/RESEARCH_NOTES.md), [AI.md](AI.md).
