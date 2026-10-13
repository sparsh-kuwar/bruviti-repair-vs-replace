# Repair vs Replace decision service

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
| `POST /decide?explain=true` | same, plus a `trace` of every check the engine ran (the UI uses this) |
| `GET /` | single-page form: enter a case or load one of the three brief examples, then press Decide |

## Run the tests

```sh
.venv/bin/python -m pytest -q
```

There are 287 tests. They run fully offline: `tests/conftest.py` disables sockets for the whole session, and FastAPI's `TestClient` calls the app in-process. They cover every rule and boundary, precedence, the three brief examples, text heuristics, validation, the HTTP contract, determinism and latency.

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

## Layout

```
app/schemas.py   request/response models, normalisation and validation
app/cost.py      D0 cost formula (exact arithmetic)
app/text.py      offline safety-hazard and contradiction detection
app/policy.py    D1-D6 rules, precedence, confidence, reasons
app/main.py      FastAPI app: /decide, /health, / (static UI)
app/static/      the page (plain HTML/CSS/JS, no CDN)
scripts/         synthetic data generator and evaluator
tests/           pytest suite and hand-labelled fixtures
```

More detail: [NOTES.md](NOTES.md) (decisions, one page), [DATA.md](DATA.md) (data and test design), [EXPLANATION.md](EXPLANATION.md) (full walkthrough), [research/RESEARCH_NOTES.md](research/RESEARCH_NOTES.md), [AI.md](AI.md).
