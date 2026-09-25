---
name: spring-review-kafka-middleware
description: Reviews Kafka safety (topics, keys, schema, consumer group, error handling, idempotency, transactions, partition impact), Redis cache-invalidation completeness (TTL alone is insufficient), and Feign/WebClient timeouts, retry safety, circuit breakers, and header propagation.
---

# Spring Review — Kafka / Redis / Middleware Safety

## Model Guidance

Capable-tier. First output line: `[spring-review-kafka-middleware] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- A partial outbox pattern implementation makes it genuinely unclear whether ghost Kafka events are possible on DB rollback — the producer and the transactional boundary are in different classes and the coordination mechanism is non-obvious
- A Reactive Redis chain has complex operator composition and the location of a potentially blocking `redisTemplate` call (vs. `reactiveRedisTemplate`) is genuinely ambiguous from reading the code

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Focus on Kafka producers/consumers, `@Cacheable`/`@CacheEvict` usages, `redisTemplate` calls, and Feign/WebClient configurations.

---

## Phase 6 — Kafka / Redis / Middleware Safety

### 6.1 Kafka Changes

Per change to Kafka producer or consumer:

| Check | What to verify |
|-------|---------------|
| **Topic name** | Topic constant or string not accidentally renamed/typo-ed. |
| **Message key** | Business key used (not null) to ensure ordering and idempotency on consumer side. |
| **Payload schema** | New/removed fields in event DTO — downstream consumers must tolerate new schema (backward compatible by default). |
| **Consumer group** | Group ID not changed inadvertently (causes replay from beginning). |
| **Error handling** | `SeekToCurrentErrorHandler`/`DefaultErrorHandler` configured; DLT exists for poison messages. |
| **Consumer idempotency** | `@KafkaListener` handler checks for duplicate `eventId` before processing. |
| **Transaction support** | If both DB and Kafka writes occur, are they in single transaction or coordinated via outbox? |
| **Partition impact** | Changing message key changes partition assignment, potentially breaking ordering guarantees. |

### 6.2 Redis Changes

#### 6.2.1 Cache Invalidation Completeness (critical)

**Every piece of data cached in Redis MUST have an explicit eviction trigger for every write path that mutates that data.** TTL alone is insufficient.

Per new/modified `@Cacheable`/`redisTemplate.opsForValue().set(...)`/`redisTemplate.opsForHash().put(...)`:

1. Identify cache key and entity/data it caches.
2. Find every code path that mutates that data (create, update, delete, status change, bulk update, Kafka consumer writing same entity).
3. Verify explicit cache eviction exists on each write path:
   - `@CacheEvict(cacheNames = "...", key = "...")` on mutating method, OR
   - `redisTemplate.delete(key)` / `redisTemplate.opsForHash().delete(...)` called explicitly, OR
   - cache manager `evict()` call.
4. If any write path mutates data without eviction:

```
REDIS CACHE INVALIDATION MISSING: <cacheName / key pattern>
  Cached by: <file:line>
  Data mutated without eviction at:
    - <file:line — method that writes entity without evicting>
    - <file:line — Kafka consumer / batch job / admin endpoint>
  Risk: Stale cache served until TTL expires (<TTL value>).
  Fix: Add @CacheEvict(cacheNames = "<name>", key = "<key expr>") to each mutating method,
       or call redisTemplate.delete(resolvedKey) explicitly after DB write.
```

5. **Partial invalidation**: compound cache keys must evict ALL affected keys.
6. **Kafka consumers and scheduled jobs**: most commonly forgotten write paths.

#### 6.2.2 General Redis Safety

| Check | What to verify |
|-------|---------------|
| **Key format** | Cache key pattern not changed in way that orphans existing cached entries. |
| **TTL** | TTL is safety net only — explicit eviction is primary. TTL > 1 hour on mutable data without explicit eviction is red flag. |
| **Thundering herd** | If `@CacheEvict` fires very frequently, does subsequent cache miss cause DB spike? |
| **Idempotency not Redis-only** | Idempotency state must have DB-level backup; do not rely solely on Redis TTL. |
| **Serialization** | If cached object's class changes (new fields, renamed, type changes), deserialization of existing entries will fail with `SerializationException`. Plan cache flush before deploying. |
| **Null caching** | Ensure `@Cacheable` does not cache `null` responses unless explicitly intended. Use `unless = "#result == null"` when appropriate. |
| **Reactive Redis** | In WebFlux, use `ReactiveRedisTemplate` — do not call `redisTemplate.opsForValue().get(...)` (blocking) inside reactive chain. |

### 6.3 Other Middleware / External Calls

| Check | What to verify |
|-------|---------------|
| **Feign / WebClient timeout** | New external call has configured timeout; missing timeout = thread starvation. |
| **Retry policy** | Retryable operation is actually idempotent; non-idempotent calls (e.g. payment) must NOT be auto-retried. |
| **Circuit breaker** | Resilience4j/Hystrix configured for new external dependency. |
| **Header propagation** | Trace ID/correlation ID forwarded to downstream service. |

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
KM-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `kafka, redis_invalidation, redis_safety, middleware`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `KM: no findings.` + checks summary.

---

## Constraints

- **Redis TTL is not eviction**: Every write path must have explicit eviction — absence is P0.
- **Kafka consumers are write paths**: Kafka consumer updating entity must also evict cache.
- **Partial invalidation**: Compound cache keys must evict ALL variants.
- **Read before commenting**: Always read actual `@Cacheable` and write-path methods before making a finding.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
