---
name: spring-api-load-test
description: >-
  Load-tests a Spring Boot API endpoint with k6 — generates the script, runs
  it, reports latency percentiles/throughput/error rate against thresholds,
  and traces slow endpoints back through controller/service/repository code
  to find the likely cause. Handles async/fire-and-forget endpoints too —
  polls a status endpoint to measure true end-to-end completion time, not
  just the HTTP ack, and traces into Kafka producer/consumer code when that's
  slow. Optional Kafka consumer-lag mode runs alongside REST flow — polls
  consumer group lag during burst, checks whether consumer thread blocks on
  downstream call, verifies sync→async dispatch fixes. Use when asked to
  "load test", "performance test", "benchmark", or "stress test" an API
  endpoint, to check why an endpoint (or its async flow) feels slow under
  load, or to verify a Kafka consumer isn't blocking. Local/dev targets only
  by default — asks before hitting anything else.
---

# Spring — API Load Test

## Model Guidance

Capable-tier. First output line: `[spring-api-load-test] running on: {model} (capable-tier)`

Root-cause step needs real code reasoning — not a fast-tier summarization task.

---

## Core Rule

k6 generates load, skill reads result + code. Never invent latency numbers — every number traces back to actual k6 run. Local/dev targets only, unless user confirms otherwise (Step 1). Breached threshold → dig into code for cause (Step 6), don't stop at numbers.

---

## Step 0 — Gather Target & Load Profile

**Environment + host — ask every run, before anything else, no exceptions:**

1. "Local, or lower env (dev/staging)?"
2. **Local** → confirm host (e.g. `http://localhost:8080`) — check project config if not obvious, still say it back for confirmation.
3. **Lower** → ask exact host explicitly. Never infer/guess host from deployment repo's naming convention and treat as settled — guessed hostname can be flat wrong even when everything else checks out (happened once: convention guess `x-message.qa2-sg.cld` vs actual `message.qa2-sg.cld`). Deployment-repo config can inform a candidate, user confirms actual host before use.

User already stated both environment and exact host unprompted in same message → repeat back for confirmation, don't ask cold.

Rest of target, ask only what's missing. Required:

- **Path/endpoint**: e.g. `/api/orders/123` — combined with the confirmed host from above
- **Method**: GET/POST/PUT/DELETE — default GET
- **Auth/headers**: bearer token, cookie, custom headers — optional. Never ask user to paste real prod credential inline; env var reference fine (`__ENV.AUTH_TOKEN`)
- **Body**: JSON payload for POST/PUT — optional

Load profile — default if unspecified:
```
ramp 0→10 VUs over 10s, hold 10 VUs for 30s, ramp down over 10s
```
Heavier ask ("stress test", "find breaking point") → ramp target VUs higher (e.g. 0→100), state in report. Lighter ask ("smoke test") → 1 VU, few iterations.

Thresholds — default if unspecified:
```
p95 latency < 500ms
error rate  < 1%
```
State whichever defaults used in final report — never apply silently.

**Async / fire-and-forget endpoint** (returns ack immediately, real work happens in Kafka consumer downstream) — ack latency alone means little. Need:

- **Status endpoint**: URL template to poll for completion, e.g. `GET /api/orders/{id}` — id substituted from initial response
- **ID field**: where to pull id from initial response (JSON field, or `Location` header)
- **Status field + terminal value(s)**: e.g. field `status`, terminal `COMPLETED`/`FAILED`

User already knows this shape → take it as given, skip discovery below.

User doesn't know it off-hand → **discover it from code, then confirm**:
1. Grep controllers for a `GET` handler under same base path as target (e.g. target is `POST /api/orders` → look for `GET /api/orders/{id}` in the same controller or a sibling one).
2. Read its response DTO. Look for status-shaped field by name (`status`, `state`, `orderStatus`, ...) or an enum-typed field.
3. Field is an enum → read the enum class, pick terminal-looking value(s) by name (`COMPLETED`, `SUCCESS`, `DONE`, `FAILED`, `ERROR`, `CANCELLED`, ...).
4. Show what got found — endpoint, field, candidate terminal value(s) — and ask user to confirm or correct before generating anything. Never silently commit to a guessed field/value.
5. Nothing plausible found → fall back to asking user directly for the three items above.

Also need, regardless of how the status endpoint got determined:
- **Poll interval + timeout**: default 500ms interval, 30s timeout if unspecified — say so if defaulted
- **E2E completion threshold**: never default — async SLAs vary too much by domain (Kafka reconciliation flow vs webhook fan-out have nothing in common). Ask explicitly; don't proceed to Step 3 for async flow without answer.

No status endpoint exists at all (discovery found nothing, user confirms none exists) → fall back to ack-latency-only, say plainly number doesn't cover real completion time.

**Kafka consumer-lag mode** (optional, additive — runs alongside REST flow, doesn't replace it, since REST call usually triggers Kafka publish):

Trigger: target is Kafka-consumer-side behavior — verifying sync→async dispatch fix, checking whether consumer thread blocks on downstream call — not pure REST latency.

Discover, never guess — same principle as host discovery above:
1. **Topic** — grep producer code for topic constant (e.g. `KafkaEventNames.java`) and `@KafkaListener` annotation consuming it.
2. **Consumer group candidate** — read `spring.kafka.consumer.group-id` from properties. Repo value can drift from live cluster — verify before trusting (seen firsthand: repo said `message-consumer-QA2`, live group on qa2 was `message-consumer-QA2-new-test`).
3. **Verify candidate against live cluster**: `kafka-consumer-groups --bootstrap-server {host} --describe --group {candidate}` — confirm target topic appears, active member present, offsets plausible. Doesn't match → list candidates via `--list` filtered by service/topic keyword, check each.
4. **Bootstrap broker(s)** — ask user explicitly. Same never-guess-hostname rule as HTTP host above.

---

## Step 1 — Safety Gate

Environment already confirmed explicitly in Step 0 — this step acts on it, doesn't re-derive it.

- **Local** → proceed straight to reachability check below.
- **Lower** → stop first, ask user to confirm they own the environment and authorize load against it. Load testing = controlled denial-of-service — never run without that confirmation, even though host was already stated in Step 0.

Confirmed → quick reachability check before generating anything: `curl -I {target}` (or `Test-NetConnection {host} -Port {port}` on PowerShell). Non-local host often needs VPN — command runs on user's actual machine, goes through whatever VPN tunnel already up, same as user running it themselves. Two failure shapes, don't conflate:

- **Unreachable** (timeout, DNS fail, connection refused) → stop, tell user: check VPN connected, check hostname/routing (split-tunnel VPNs may not route target subnet). Don't generate script against unreachable host.
- **Reachable but non-2xx/3xx** (e.g. 404, 401) → proceed, note it — likely path/auth needs adjusting, not connectivity problem.

**Kafka mode** → same gate applies to brokers as HTTP host. Lower env → stop, confirm user owns brokers, authorizes polling, before proceeding. Never run against brokers without confirmation, even if address already stated in Step 0.

---

## Step 2 — Check k6 Installed

Run `k6 version`. Not found → stop, tell user to install, no silent fallback to hand-rolled script:

```
winget install k6.k6
# or
choco install k6
```

**Kafka mode** also needs `kafka-consumer-groups` on PATH (from `brew install kafka` — full Kafka CLI incl. `kafka-topics`, `kafka-get-offsets`, no `.sh` suffix on Homebrew). Run `kafka-consumer-groups --version` (or `--help` if unsupported). Not found → stop, tell user to install, same gate as k6.

---

## Step 3 — Reuse or Generate the Script

Scripts live at `scripts/load-tests/{endpoint-slug}.k6.js` in the target repo (slug from path, e.g. `api-orders-id`) — persistent, reusable across runs, not thrown away after one test.

Check first: `scripts/load-tests/{endpoint-slug}.k6.js` already exist?

- **Yes** → read it before touching anything.
  - Target/method/body shape match Step 0 → reuse as-is. Only load profile/thresholds changed this run → patch just `options.stages`/`options.thresholds` in place, leave headers/async-polling logic untouched, tell user what changed. Nothing changed → skip straight to Step 4, don't rewrite correct file.
  - Slug matches but resolved target differs (edge case — path collision) → stop, flag mismatch, ask before overwriting. Never silently clobber existing script.
- **No** → generate fresh, per templates below.

```js
import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.TARGET_URL || '{resolved target}';
const AUTH_TOKEN = __ENV.AUTH_TOKEN || '';

export const options = {
  scenarios: {
    default: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 10 },
        { duration: '30s', target: 10 },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const headers = AUTH_TOKEN ? { Authorization: `Bearer ${AUTH_TOKEN}` } : {};
  const res = http.get(BASE_URL, { headers });
  check(res, { 'status is 2xx': (r) => r.status >= 200 && r.status < 300 });
}
```

Swap `http.get` for `http.post(BASE_URL, JSON.stringify(body), { headers: {...headers, 'Content-Type': 'application/json'} })` for POST/PUT. Stages and thresholds come from Step 0 — fill in user's ask or defaults, never leave template numbers unexamined.

Secrets never hardcoded into script — always `__ENV.*`, tell user to export before running:

```bash
export AUTH_TOKEN=...   # or $env:AUTH_TOKEN = "..." on PowerShell
```

**Async endpoint** (Step 0 gave a status endpoint) — extend `default function` to poll after the initial call, track completion time as separate `Trend` metric:

```js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const e2eDuration = new Trend('e2e_completion_duration');
const POLL_INTERVAL_S = 0.5;
const MAX_POLLS = 60;

export default function () {
  const start = Date.now();
  const res = http.post(BASE_URL, JSON.stringify(body), { headers: {...headers, 'Content-Type': 'application/json'} });
  check(res, { 'ack is 2xx': (r) => r.status >= 200 && r.status < 300 });

  const id = res.json('{idField}');
  let completed = false;
  for (let i = 0; i < MAX_POLLS; i++) {
    sleep(POLL_INTERVAL_S);
    const statusRes = http.get(`{statusUrlTemplate}`.replace('{id}', id), { headers });
    if (statusRes.json('{statusField}') === '{terminalValue}') {
      completed = true;
      break;
    }
  }
  if (completed) e2eDuration.add(Date.now() - start);
  check(null, { 'completed within timeout': () => completed });
}
```

Add matching threshold to `options.thresholds`: `e2e_completion_duration: ['p(95)<{user-given ms}']` — value comes straight from Step 0's answer, never invented.

**Kafka mode** — generate lag-polling script alongside k6 script, same lifecycle (check-before-generate, patch-not-rewrite): `scripts/load-tests/{endpoint-slug}.kafka-lag.sh`

Already exists → read before touching. Bootstrap/group/topic match this run → reuse as-is. Differ → patch just those values, tell user what changed.

```bash
#!/bin/bash
# polls consumer lag every 3s, appends one row per partition to CSV
BOOTSTRAP="{bootstrap-brokers}"
GROUP="{verified-group}"
TOPIC="{topic}"
OUT="scripts/load-tests/{endpoint-slug}.lag.csv"

echo "timestamp,topic,partition,current_offset,log_end_offset,lag" > "$OUT"
while true; do
  kafka-consumer-groups --bootstrap-server "$BOOTSTRAP" --describe --group "$GROUP" 2>/dev/null \
    | awk -v topic="$TOPIC" -v ts="$(date +%s)" '$1==topic {print ts","$1","$2","$4","$5","$6}' >> "$OUT"
  sleep 3
done
```

---

## Step 4 — Run It

```bash
k6 run --summary-export=scripts/load-tests/{endpoint-slug}.result.json scripts/load-tests/{endpoint-slug}.k6.js
```

Run directly — Step 1's gate is the safety check, not a second per-run confirmation. Execution fails (connection refused, script error) → report raw error, don't guess result.

**Kafka mode — baseline check** (before running load): `kafka-consumer-groups --bootstrap-server {host} --describe --group {group}` once. Lag at/near 0 → proceed, healthy starting point. Existing backlog → flag it, results get contaminated, ask user: proceed anyway or wait for drain first.

**Kafka mode — run concurrently**: start poller in background (`bash scripts/load-tests/{slug}.kafka-lag.sh & echo $!` — capture PID), run k6 against REST/producer endpoint per steps above, then let poller keep running past k6 completion (2-3x load duration) to observe drain — don't kill it the instant k6 exits. Stop poller (`kill {PID}`) once drain observed or timeout reached.

---

## Step 5 — Assess Results

Read `result.json`. Pull from `metrics`:

| Metric | JSON path |
|---|---|
| p50/p90/p95/p99 | `http_req_duration.values["med"/"p(90)"/"p(95)"/"p(99)"]` |
| avg / max | `http_req_duration.values["avg"/"max"]` |
| error rate | `http_req_failed.values.rate` |
| throughput | `http_reqs.values.rate` (req/s) |
| total requests | `http_reqs.values.count` |
| e2e completion (async only) | `e2e_completion_duration.values["p(95)"]` — plus completion rate from `completed within timeout` check pass rate |

Compare p95/error rate (and e2e p95 for async) against Step 0's thresholds. `PASS` or `FAIL` per threshold — no vague "looks ok." Async run where completion check pass rate < 100% → flag separately, some requests never completed within timeout, not just slow.

All pass → report numbers, stop here.
Any fail → continue to Step 6.

**Kafka mode — additional fields**, read from `{slug}.lag.csv`:

| Field | How derived |
|---|---|
| Peak lag per partition | max `lag` value per partition during burst window |
| Time-to-drain-to-zero | timestamp lag last hits 0 minus timestamp load stopped |
| Offset progression | `current_offset` climbing continuously during burst = progress; flat/stalled = blocking |

Interpretation — inference from throughput/lag shape, not direct thread-identity proof, say so plainly in report:

- **Async-healthy pattern**: lag rises proportionally less than total injected messages, drains within roughly one order of magnitude of burst duration, offsets never stall.
- **Sync-regressed pattern**: lag climbs close to 1:1 with injected messages, drains slowly, bounded by per-message downstream call latency.

Dedicated thread-assertion unit test exists in repo → point to it as definitive check, treat load test as behavioral corroboration only, not replacement.

Never treat REST ack latency and consumer lag as same signal — fire-and-forget REST endpoint can look perfectly healthy while consumer behind it fully blocked. State explicitly which one this profile actually measures.

---

## Step 6 — Root-Cause Dig (thresholds breached)

Trace target URL path back to code:

1. Grep controllers for `@RequestMapping`/`@GetMapping`/`@PostMapping`/etc matching the path → find handler method.
2. Read handler → follow into `@Service` method(s) it calls.
3. Read service method → follow into repository/external calls it makes.

**Async threshold breached** (e2e completion slow, not just ack) — trace past the producer, into the consumer side:

4. Handler/service publishes via `KafkaTemplate.send(...)` → note topic name.
5. Grep for `@KafkaListener` on that topic → read consumer method.
6. Read consumer method → follow into whatever it calls to reach the terminal status update (service/repository writing the `status` field Step 0's poll checks for).

Extra async-specific checks:

| Risk | Where to look |
|---|---|
| Consumer lag / undersized concurrency | `@KafkaListener(concurrency = ...)` too low for partition count, or consumer group falling behind — full safety review belongs to `spring-review-kafka-middleware`, reference it, don't redo here |
| Slow/blocking work inside consumer | external HTTP call, heavy DB write, or synchronous retry loop inside the listener method |
| Retry/backoff inflating completion time | consumer configured with long backoff before retrying a transient failure — completion time includes every retry wait |
| DLQ silently swallowing | message routed to dead-letter topic — status never reaches terminal value, poll always times out (completion rate < 100%, not just slow) |

Ack-latency-shaped bottleneck → check, ranked by how often it's the actual cause:

| Risk | Where to look |
|---|---|
| N+1 query | loop calling repository method per iteration |
| Missing index / full scan | `@Query`/`mongoTemplate`/`jdbcTemplate` filtering on non-indexed field — full ESR breakdown belongs to `spring-review-query-performance`, reference it, don't redo here |
| Blocking call in reactive chain | `block()`/JDBC call inside `Mono`/`Flux` without `subscribeOn(Schedulers.boundedElastic())` |
| Sequential external calls | multiple Feign/WebClient/RestTemplate calls in series with no dependency between them — could run concurrently |
| No caching on repeated lookup | same lookup key fetched from DB every request, no `@Cacheable` |
| Undersized connection/thread pool | Tomcat `server.tomcat.threads.max` or DB pool size (`hikari.maximum-pool-size`) lower than tested VU count — saturation, not app logic |
| Unbounded response | `findAll()`/no `Pageable` on large table, serializing more than endpoint needs |

Report each hit as `file:line` + one-line reason. No hit found → say so plainly, don't force a finding.

Query-shaped bottleneck → tell user to run `spring-review-query-performance` for full index recommendation, don't duplicate ESR analysis inline.

---

## Return Format

```
[spring-api-load-test] running on: {model} (capable-tier)

Target: {method} {url}  (gate: local/dev | confirmed by user)
Profile: {VUs/stages}, thresholds: p95<{x}ms, error_rate<{y}%[, e2e_p95<{z}ms — async]

Results:
  p50={..}ms  p90={..}ms  p95={..}ms  p99={..}ms  max={..}ms
  throughput={..} req/s   requests={n}   error_rate={..}%
  p95 threshold: PASS|FAIL
  error_rate threshold: PASS|FAIL
  [async] e2e completion p95={..}ms   completed_rate={..}%
  [async] e2e threshold: PASS|FAIL
  [kafka] peak lag per partition: {p0}={..} {p1}={..} ...
  [kafka] time-to-drain-to-zero: {..}s after load stopped
  [kafka] offset progression: climbing continuously | flat/stalled
  [kafka] pattern: async-healthy | sync-regressed — {one-line reason}

Script:  scripts/load-tests/{slug}.k6.js  [reused | generated]
Result:  scripts/load-tests/{slug}.result.json
[kafka] Poller: scripts/load-tests/{slug}.kafka-lag.sh  [reused | generated]
[kafka] Lag CSV: scripts/load-tests/{slug}.lag.csv

[if breached] Likely cause:
  {file}:{line} — {one-line reason}
  ...
[if none found]
  No obvious cause found in code — check infra (connection pool, thread pool, downstream latency, consumer lag).
```

---

## Constraints

- **Never target non-local/dev host without explicit confirmation** — load testing is controlled DoS, treat it that way.
- **Never hardcode secrets in generated script** — `__ENV.*` only.
- **Never fabricate results** — no k6 run, no numbers. k6 not installed or run errors → say so, stop.
- **State defaults used** — load profile/thresholds not explicitly requested get called out in report, never applied silently.
- **Root-cause is read-only** — report findings, don't edit production code. Separate follow-up work.
- **Don't redo `spring-review-query-performance`'s job** — point to it for index/ESR depth, don't re-derive compound index recommendations here.
- **Don't redo `spring-review-kafka-middleware`'s job** — point to it for consumer/producer safety depth, don't re-derive here.
- **Never default an e2e completion threshold** — ask. Ack-latency defaults (p95<500ms) don't transfer to async business operations.
- **Completion rate < 100% is its own finding** — some requests never reaching terminal status (DLQ, dropped message) is a correctness issue, not just a latency number. Never fold it silently into the p95.
- **Scripts are reusable, not disposable** — check `scripts/load-tests/{slug}.k6.js` before generating. Never blindly overwrite an existing one; patch only what this run's ask actually changed.
- **Kafka mode never guesses topic, consumer group, or broker** — discover from code, verify group against live cluster, ask user for broker address. Same never-guess rule as HTTP host.
- **Same lower-env authorization gate applies to Kafka brokers as HTTP host** — never poll brokers without explicit confirmation user owns environment.
- **Kafka lag pattern is inference, not thread-identity proof** — say so in report. Dedicated thread-assertion unit test in repo, if one exists, is the definitive check; load test is behavioral corroboration only.
- **Never conflate REST ack latency with consumer lag** — state explicitly which one a given load test profile measures. Fire-and-forget endpoint can ack fine while consumer behind it fully blocked.
- **Kafka mode runs alongside REST flow, not instead of it** — REST call usually triggers the Kafka publish being measured.
