# Performance

Load, concurrency and stress results for `POST /decide`. Every number in the **Measured** sections comes from `load/results/steps.csv` (one stress run per worker count, 2026-10-13) or from `scripts/profile_decide.py`. Sections marked **Interpretation** are conclusions drawn from those numbers. The method and the defect found while testing are also in [TESTING.md](TESTING.md) §6 and DEF-21.

## 1. Environment and commands

| | |
|---|---|
| Machine | Apple M3 MacBook Air, 8 cores (4 performance + 4 efficiency), macOS 26.5.1 |
| Software | Python 3.13.7; FastAPI 0.128.8, Starlette 0.41.3, Pydantic 2.13.5, uvicorn 0.39.0 (h11 parser, asyncio loop; no uvloop/httptools); Locust 2.46.7, psutil 7.2.2 |
| Server | `uvicorn app.main:app --host 127.0.0.1 --workers N --no-access-log`, N = 1, 2, 4. `./run.sh` starts the N = 1 configuration |
| Load generator | Locust, 4 processes, **on the same machine** as the server (they share the 8 cores) |
| Simulated user | One support agent: `POST /decide?explain=true` (as the page sends it), then waits 0.5–1.5 s. Cases rotate through the 49 fixture cases in `tests/fixtures/`. Request timeout 10 s |
| Ramp | Steps of 25 → 50 → … → 14,000 users. Each step: warm-up (5 s plus spawn time at 400 users/s), stats reset, 15 s measured. The run stops at the first step that breaks |
| Breaking point | p95 latency > 1 s (the brief's per-request budget) **or** error rate > 1% |
| CPU | Process CPU time from `psutil` over each measured window: server parent plus all workers, and all Locust processes, reported in cores |

```sh
pip install -r requirements-load.txt
.venv/bin/python scripts/stress.py --workers 1 2 4      # ~35 min; writes load/results/steps.csv
.venv/bin/python scripts/profile_decide.py               # CPU per request by stage, in-process
.venv/bin/python -m pytest -q tests/test_concurrency.py  # correctness under parallel requests
```

## 2. Measured results

### 2.1 Summary per worker configuration

| Workers | Peak throughput (req/s) | at users | Last step within budget | First step over budget | Errors (all steps) |
|---|---|---|---|---|---|
| 1 | 2,885.1 | 3,000 | 4,000 users: p95 720 ms, max 785 ms | 5,000 users: p95 1,200 ms | 0 |
| 2 | 4,953.6 | 5,000 | 7,000 users: p95 980 ms, max 1,200 ms | 8,000 users: p95 1,800 ms | 0 |
| 4 | 5,913.4 | 7,000 | 7,000 users: p95 640 ms, max 996 ms | 8,000 users: p95 1,200 ms | 0 |

Every configuration broke on latency. No step of any run recorded an error.

### 2.2 Steps from 1,000 users upward

Below 1,000 users every configuration served the offered load (about 1 request per user per second) with p95 ≤ 8 ms and max ≤ 38 ms. Full data: `load/results/steps.csv`.

**1 worker**

| Users | req/s | p50 | p95 | p99 | Max | Errors | Server CPU | Locust CPU |
|---|---|---|---|---|---|---|---|---|
| 1,000 | 997.9 | 1 | 4 | 5 | 15 | 0 | 0.58 | 0.20 |
| 1,500 | 1,494.2 | 1 | 3 | 4 | 12 | 0 | 0.60 | 0.21 |
| 2,000 | 1,990.1 | 1 | 3 | 6 | 38 | 0 | 0.72 | 0.25 |
| 2,500 | 2,485.4 | 2 | 16 | 47 | 63 | 0 | 0.89 | 0.31 |
| 3,000 | 2,885.1 | 19 | 110 | 170 | 182 | 0 | 1.02 | 0.37 |
| 4,000 | 2,581.7 | 520 | 720 | 760 | 785 | 0 | 1.03 | 0.49 |
| 5,000 | 2,460.3 | 1,000 | 1,200 | 1,300 | 1,295 | 0 | 1.02 | 0.59 |

**2 workers**

| Users | req/s | p50 | p95 | p99 | Max | Errors | Server CPU | Locust CPU |
|---|---|---|---|---|---|---|---|---|
| 1,000 | 999.2 | 1 | 3 | 4 | 7 | 0 | 0.74 | 0.23 |
| 2,000 | 1,997.5 | 1 | 1 | 2 | 8 | 0 | 0.77 | 0.26 |
| 3,000 | 2,997.1 | 1 | 2 | 3 | 30 | 0 | 1.20 | 0.41 |
| 4,000 | 3,986.9 | 1 | 4 | 30 | 81 | 0 | 1.54 | 0.51 |
| 5,000 | 4,953.6 | 3 | 53 | 120 | 148 | 0 | 1.90 | 0.64 |
| 6,000 | 4,875.7 | 210 | 430 | 460 | 486 | 0 | 2.05 | 1.01 |
| 7,000 | 4,073.3 | 660 | 980 | 1,000 | 1,200 | 0 | 2.04 | 1.43 |
| 8,000 | 3,587.7 | 1,200 | 1,800 | 2,000 | 2,025 | 0 | 2.02 | 1.75 |

**4 workers**

| Users | req/s | p50 | p95 | p99 | Max | Errors | Server CPU | Locust CPU |
|---|---|---|---|---|---|---|---|---|
| 1,000 | 997.1 | 1 | 2 | 6 | 104 | 0 | 0.64 | 0.20 |
| 2,000 | 1,988.1 | 1 | 1 | 1 | 8 | 0 | 0.85 | 0.28 |
| 3,000 | 2,995.9 | 1 | 1 | 2 | 13 | 0 | 1.29 | 0.40 |
| 4,000 | 3,994.6 | 1 | 2 | 3 | 25 | 0 | 1.75 | 0.55 |
| 5,000 | 4,911.9 | 1 | 110 | 260 | 352 | 0 | 2.49 | 0.90 |
| 6,000 | 5,412.3 | 3 | 640 | 910 | 1,150 | 0 | 3.15 | 1.34 |
| 7,000 | 5,913.4 | 68 | 640 | 890 | 996 | 0 | 3.74 | 1.95 |
| 8,000 | 4,659.0 | 730 | 1,200 | 1,400 | 1,604 | 0 | 3.54 | 2.29 |

Latencies are in ms, CPU in cores. Locust approximates percentiles by rounding (to 2 significant figures above 100 ms), so a percentile can read slightly above the exact maximum: 1 worker at 5,000 users shows p99 1,300 against a max of 1,295.

### 2.3 CPU per request by stage

In-process, no HTTP, 10,000 requests with `explain=true` over the 49 fixture cases (`scripts/profile_decide.py`):

| Stage | µs per request | Share of in-process time |
|---|---|---|
| Parse + validate (Pydantic) | 15.6 | 12% |
| Rules engine (`policy.decide`) | 97.1 | 73% |
| Response model | 8.8 | 7% |
| JSON encode | 11.3 | 8% |
| **Total** | **132.8** | |

In `cProfile`, the largest single cost was regex search (`re.Pattern.search`, about 1.34 M calls per 10,000 requests) in the symptom-text checks in `app/text.py`.

**Derived** from the measured numbers above: CPU per request over HTTP at the 1-worker peak = 1.02 cores ÷ 2,885.1 req/s ≈ **354 µs**. Of that, about 133 µs (≈38%) is the in-process work above, and the remaining ≈221 µs (≈62%) is spent outside it: HTTP parsing, routing and the thread-pool hand-off.

### 2.4 Correctness under concurrency

`tests/test_concurrency.py` sends the 49 fixture cases 5 times each from 16 threads, with and without `explain`, and compares every response with the one the same case gets when sent alone. Both tests passed in the latest recorded suite run ([TESTING.md](TESTING.md) §5: 310 passed, 0 failed) and in CI on the commit that added them.

### 2.5 Rejected run (load-generator defect)

The first stress run recorded errors at exactly 5,000 users with 2, 4 and 8 workers (6.0%, 9.8% and 8.7%), all `OSError: [Errno 49] Can't assign requested address`. The cause was in Locust's HTTP client, not the service: a `select()` call fails on file descriptors above 1024, which made the client reconnect on every request until the machine ran out of ephemeral ports. After fixing it with `poll()`, the same load gave 0 errors. Details are in TESTING.md DEF-21. Those results are kept in `load/results/steps-buggy-rig.csv` and are **not** used anywhere above.

## 3. Bottleneck (interpretation)

**With one worker the limit is CPU in the single Python process.**

- **Evidence.** Throughput rises with load until server CPU reaches 1.02 cores at 3,000 users. After that it stops rising and then falls (2,885 → 2,582 → 2,460 req/s) while CPU stays at about 1.0 core. Meanwhile p50 latency grows from 19 ms to 1,000 ms.
- **Why one core.** The `/decide` handler is synchronous and runs in Starlette's thread pool, and Python's GIL lets only one thread run Python code at a time. So the process cannot use a second core, however many threads it has.
- **Not the load generator.** Locust used at most 0.59 cores at those steps.
- **Overload makes each request more expensive.** CPU per request rose from ≈354 µs at the peak to ≈415 µs at 5,000 users (1.02 ÷ 2,460.3), about 17% more. A likely explanation is the cost of managing thousands of open connections and queued requests; this was not profiled separately.
- **Workers confirm it.** 2 workers reached 4,953.6 req/s (1.72× one worker) on about 2 cores, and the breaking point moved from 5,000 to 8,000 users.
- **Past 2 workers the test machine is the limit.** 4 workers gained only 19% over 2 (5,913.4 vs 4,953.6 req/s). At that peak the server used 3.74 cores and Locust 1.95, on a machine whose 8 cores include 4 slower efficiency cores. This shows the shared laptop running out of capacity; it does not establish a limit of the service.
- **Where the CPU goes.** Most of a request's CPU (≈62%) is the web stack, not the policy. The rules engine is about 27% of the total, dominated by regex scanning of the symptom text.

## 4. Engineering decisions

| Decision | Reason |
|---|---|
| `./run.sh` keeps **1 worker** | The brief requires the API and page to be served by one process on port 8000. Measured: within the 1 s budget up to 4,000 concurrent agents (≈2,600 req/s) |
| Breaking point = p95 > 1 s, not "first error" | The service queues rather than fails. No step recorded an error, so an error-only criterion would not have triggered before latency passed the brief's budget |
| Step ramp with think time | Users map to concurrent agents, and each step is measured at steady state |
| Server and Locust CPU recorded together | So that a load-generator limit is not mistaken for a service limit |
| Response cache **not** shipped | A cache keyed on the full case (including `case_id`) would see no repeats in real traffic. Even on a hit it could only skip the engine and response building (≈117 of ≈354 µs) |
| Load-test dependencies kept out of `requirements.txt` | `requirements-load.txt` is optional; the service and the offline test suite do not need Locust |

## 5. Possible improvements (not implemented, not measured)

1. **Workers equal to the core count, or more instances behind a load balancer.** The service is stateless, so it scales out without code changes. Expected gain: roughly linear while cores are free, based on the 1 → 2 worker result.
2. **Bounded concurrency** (`uvicorn --limit-concurrency`, or a limit at a proxy), so overload returns a fast 503 instead of slowing every request and losing throughput (§3).
3. **A faster HTTP layer** (`uvicorn[standard]` adds `httptools` and `uvloop`), aimed at the ≈62% spent outside the application code.
4. **Fewer regex passes over the symptom text**, for example by merging patterns, aimed at the rules engine's ≈27%.

The size of each gain is unknown until measured with the same `scripts/stress.py` run.

## 6. Not tested

- **Load from a separate machine.** Every run shared one laptop with the load generator, so results for more than 2 workers are limited by the test machine.
- **8 workers.** The run was started and stopped before completing; no results are reported.
- **Repeat runs.** Each configuration was run once, so run-to-run variance is unknown.
- **Soak testing** (hours at steady load): memory growth and long-run stability.
- **Production-like conditions:** Linux server hardware, real network latency, TLS, a reverse proxy.
- **Load with `explain=false`, and load with maximum-size inputs** (for example 200 parts and very long symptom text). Large inputs are covered only by the single-request latency test (TESTING.md TC-007).
- **Behaviour under `--limit-concurrency`** or any other overload protection.
- **Live sampling profile of the server under load.** py-spy needs root on macOS; it was not run. The stage breakdown in §2.3 is in-process only.
