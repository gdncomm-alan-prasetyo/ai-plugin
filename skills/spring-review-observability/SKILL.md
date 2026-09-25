---
name: spring-review-observability
description: Reviews observability and logging gaps. Checks PII in logs, MDC/trace ID propagation in new entry points, missing Micrometer metrics, health indicators for new dependencies, and log level discipline.
---

# Spring Review — Observability & Logging

## Model Guidance

Capable-tier. First output line: `[spring-review-observability] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- A logged object's class has complex nested DTOs or class inheritance and it is genuinely ambiguous whether any reachable field is PII under the defined list (email, phone, national ID, full name, DoB, device ID, IP, financial account, card, address)
- A state-changing method's classification as a "new critical operation" requiring an audit trail is genuinely ambiguous — the method does mutate state but it is unclear whether business rules demand an audit log for it

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

---

## Phase 13 — Observability & Logging

### 13.1 PII in Log Statements

Scan **all** changed files — services, repositories, Kafka listeners, scheduled jobs — for log statements that include:
- Full entity objects (e.g. `log.info("entity: {}", entity)` where entity has PII fields)
- String interpolation containing user-supplied data without masking
- Exception messages echoing user input

**PII fields to flag**: email, phone number, national ID/tax ID, full name, date of birth, device ID, IP address, financial account number, card number, physical address.

Also check:
- Kafka event payloads logged at DEBUG level containing PII.
- Exception messages including user-supplied data.
- HTTP request/response logging middleware logging full bodies without field-level masking.

### 13.2 MDC / Trace ID Propagation

| Check | What to verify |
|-------|---------------|
| **MDC not set in new entry points** | New `@KafkaListener`, new `@Scheduled` job, new `@RestController` endpoint — does method set `MDC.put("traceId", ...)` before any log call? For controllers, verify filter covers new path. |
| **MDC cleared on exit** | If MDC set manually, must be cleared (`MDC.clear()`) in `finally` block or `try-with-resources` to avoid leaking into next request on same thread. |
| **Trace ID forwarded to downstream** | Feign clients, `WebClient`, Kafka producers should forward trace ID as header (e.g. `X-Request-Id`, `X-Trace-Id`). |

### 13.3 Missing Metrics

| Trigger | What metric to add |
|---------|-------------------|
| New endpoint processing business transaction | `Counter` on success and each failure type; `Timer` wrapping execution. |
| New Kafka consumer | Counter for messages received, processed successfully, failed. |
| New external HTTP call | Timer (captures latency); counter for success/timeout/error. |
| New scheduled job | Counter for runs completed/failed; timer for execution duration. |

```
OBSERVABILITY GAP: No metrics for <operation>
  Location: <file:line>
  Suggested metric: meterRegistry.counter("<service>.<operation>.success").increment()
                    meterRegistry.counter("<service>.<operation>.error", "reason", errorCode).increment()
```

### 13.4 Health Indicators

If new external dependency (database, external API, message broker, Redis) introduced, corresponding Spring Boot `HealthIndicator` should be added (or verified as existing) so `/actuator/health` reflects dependency's status.

### 13.5 Log Level Discipline

| Risk | What to detect |
|------|---------------|
| **`log.debug()` in high-frequency hot path** | Debug log inside loop or frequently called method generates enormous log volume if debug accidentally enabled in production. |
| **`log.error()` for non-errors** | Using `log.error` for expected business conditions (member not found, validation fail) floods error dashboards. Use `log.warn` for expected failures; `log.error` only for unexpected system failures. |
| **No logging around new critical operations** | New financial mutation, state transition, or irreversible action should log at `INFO` before and after (with non-PII identifiers) for audit trail. |

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
OBS-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `pii_in_logs, mdc_trace, metrics, health_indicators, log_levels`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `OBS: no findings.` + checks summary.

---

## Constraints

- **PII in logs is P0**: Flag if PII fields (email, phone, national ID) directly logged.
- **MDC for every new entry point**: Kafka listeners and scheduled jobs frequently missed.
- **Log level matters**: `log.error` for "member not found" fills dashboards and masks real errors.
- **Read before commenting**: Always read actual log statement and entity/DTO class.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
