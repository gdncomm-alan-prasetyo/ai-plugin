---
name: spring-review-idempotency
description: Audits idempotency correctness (20 checks) for state-mutating endpoints, Kafka consumers, and scheduled jobs. Discovers project key convention via sibling-repo grep before scoring. Flags key scope, replay semantics, payload mismatch, races, Kafka key, Redis avoidance, IDOR, isolation level, migration safety, replay response consistency, TTL anti-pattern, and offset commit safety.
---

# Spring Review — Idempotency Audit

## Model Guidance

Capable-tier. First output line: `[spring-review-idempotency] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- Read-modify-write race in reactive `flatMap + switchIfEmpty` chain: non-obvious if unique DB index gives sufficient atomicity — can `switchIfEmpty` fire concurrently on two requests before either commits (check #4)
- `@ChangeUnit` modifies existing production data with complex rollback implications — partial execution + Mongock retry could corrupt idempotency state of already-processed records

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Focus on:
- Controllers/Routers: `*Controller.java`, `*Router.java`, `*Handler.java`
- Services: `*Service.java`, `*ServiceImpl.java`
- Repositories: `*Repository.java`, `*RepositoryImpl.java`
- Entities/Documents: `*Entity.java`, `*Document.java`
- Kafka: `*Consumer.java`, `*Listener.java`
- Scheduled jobs: `*Job.java`, `*Scheduler.java`, `*Task.java`, `*BatchProcessor.java`
- Migrations: `*.json`, `*.sql`, `*.yaml` (index definitions, `@ChangeUnit` classes)

---

## Phase 0.5 — Project Idempotency Pattern Discovery

### Step A — New or existing entity?

Check `.review-context.md` Section 3 status of changed `*Repository.java`:
- `A` → NEW entity → go to Step C.
- `M` → EXISTING entity → go to Step B.

### Step B — Existing entity: scan Section 6 for established dedup query

Scan Section 6 (Caller Analysis). Qualifies as dedup query if **both**:
1. Single-entity return: not `List<`, `Page<`, `Flux<`, `Optional<List`.
2. 2+ `And` segments (3+ equality fields) — single-field lookup is owner lookup, not dedup.

Found → record pattern, output Step D block, skip Step C. Not found → Step C.

### Step C — New entity or no pattern in cache: discover via sibling repositories

**C1 — One grep, no file reads yet**

Locate DAO source dir (`*-dao-api/src/main/java/`). Run exactly **one Grep**:
```
pattern : [A-Z]\w+ findBy\w+And\w+(And\w+)+\(
glob    : *Repository*.java
output  : content
head    : 25
```

**C2 — Classify from signatures (no file reads)**

Key type:
- **SYNTHETIC_KEY**: camelCase starts with `idempotency`, `correlationId`, `dedupKey`, `externalRef`.
- **NOT idempotency keys**: `requestId`, `traceId` — tracing/observability only, not dedup.
- **BUSINESS_KEY**: segments ending in `Id`, `Code`, `Type`, `Number`, `Status`, `Date`.
- **MIXED / UNKNOWN**: both or insufficient.

Selectivity: 2 `And` = medium, 3+ `And` = high (preferred). Pick most selective single-return method.

**C3 — Read ≤ 2 repo files only if C2 ambiguous**

Ambiguous = < 3 matching signatures or all 2-field lookups. Pick 2 files matching entity name. Use `limit: 60`.

### Step E — Entity Unique Index Scan

Verify DB-level unique constraint enforces canonical dedup key on entity model.

**E1 — Locate entity content (priority order)**

1. Entity changed in this PR → check its Section 4 diff for `@CompoundIndex`/`@Indexed`/SQL `UNIQUE` declarations. New entities (status A): full content in diff.
2. Not found in Section 4 → run one Grep in DAO entity dir:
   ```
   pattern : @CompoundIndex|@Indexed
   glob    : *<EntityName>*.java
   output  : content
   ```
3. Still not found → `found: UNKNOWN` — record in Step D, ask user in report. Don't stop review.

**E2 — Extract unique index declarations**

From entity content, collect:
- `@CompoundIndex(def = "{'f1':1,'f2':1,...}", unique = true)` on class
- `@Indexed(unique = true)` on field
- SQL: `UNIQUE KEY`, `UNIQUE INDEX`, `CONSTRAINT ... UNIQUE`
- `@CompoundIndex` without `unique = true` does **not** enforce uniqueness — do not count it.

**E2.5 — Scan migration files for existing index on dedup fields**

Run when `covers_dedup_key ≠ YES` after E2. Don't skip even if entity has no annotations.

1. Locate migration dirs: `mongock/`, `db/`, `migrations/`, `changelog/` in any module.
2. Run **one Grep** using pipe-joined dedup field names:
   ```
   pattern : <field1>|<field2>|<field3>   (from canonical_dedup_key.fields)
   glob    : *.json | *.sql | *.yaml | *.xml | *ChangeUnit*.java
   output  : content
   head    : 40
   ```
3. From grep hits, check for index creation covering **all** dedup fields:
   - MongoDB JSON/BSON: `createIndex` / `ensureIndex` object containing those field names
   - Java `@ChangeUnit`: `mongoTemplate.indexOps(...).ensureIndex(...)` or `db.getCollection(...).createIndex(...)` with those fields
   - SQL: `CREATE UNIQUE INDEX ... ON <table> (field1, field2, ...)`
4. Match → set `migration_index: YES` with file path + line. Upgrade `covers_dedup_key` to YES or PARTIAL accordingly.
5. No match → `migration_index: NO`.

**E3 — Cross-reference against canonical dedup key**

Compare index fields against `canonical_dedup_key.fields` (after E2 and E2.5):
- All dedup fields covered by one unique index → `covers_dedup_key: YES`
- Some covered, some missing → `covers_dedup_key: PARTIAL`
- No unique index found in entity annotations or migration files → `covers_dedup_key: NO`

**E4 — No-index recommendation: validate against project field patterns**

Trigger when `covers_dedup_key = NO` after E2 and E2.5.

1. Use `canonical_dedup_key.fields` from Step C as recommended index fields.
2. If `canonical_dedup_key` = UNKNOWN, run one Grep across sibling entity and migration files for common idempotency field names:
   ```
   pattern : idempotencyKey|requestId|correlationId|externalRef|dedupKey|traceId
   glob    : *.java | *.json
   output  : content
   head    : 20
   ```
   Pick most frequent field(s). Note as `inferred from project scan`. Nothing found → `UNKNOWN — ask team`.
3. Produce ESR-ordered index recommendation: equality (high-cardinality first) → sort → range.
4. Include as P1 action item with exact index DDL.

### Step D — Output discovered pattern

Produce immediately before Phase 1:

```
### Project Idempotency Pattern (discovered)

entity_under_review : <ChangedEntityName>
entity_status       : NEW | EXISTING
pattern_source      : established — same entity cache
                    | inferred — sibling repository grep
                    | inferred — sibling repository file read
                    | no pattern found

canonical_dedup_key:
  key_type              : BUSINESS_KEY | SYNTHETIC_KEY | MIXED | UNKNOWN
  fields                : [<field1>, <field2>, ...]
  precision             : HIGH (4+ fields) | MEDIUM (3 fields) | LOW (2 fields)
  example               : <RepositoryInterface>#<methodName>
  reusable              : YES | NO

gap_in_changed_code:
  current_key    : <dedup key used, or "none — no dedup check">
  key_mismatch   : YES | NO
  missing_fields : [<fields in canonical pattern absent from DTO or service lookup>]
  wrong_query    : <query if owner lookup (1–2 fields) instead of dedup>
  recommendation : <one sentence — name existing method to reuse if reusable=YES>

entity_unique_index:
  found            : YES | NO | UNKNOWN
  source           : Section 4 diff | entity file grep | not found
  index_defs       : [{ fields: [f1, f2, f3], type: @CompoundIndex(unique=true) | @Indexed(unique=true) | SQL UNIQUE }]
  migration_index  : YES | NO | NOT_CHECKED
  migration_source : <file:line> | none
  covers_dedup_key : YES | PARTIAL | NO | UNKNOWN
  uncovered_fields : [<dedup fields not covered by any unique index or migration>]
  recommended_fields : [<E4 fields — from canonical key or project scan; omit if covers_dedup_key=YES>]
```

No pattern found → `canonical_dedup_key` = UNKNOWN; continue with generic checklist only, don't block review.

---

## Phase 1 — Idempotency Audit

Per state-mutating endpoint/consumer, trace full vertical slice (Controller → Service → Repository → Entity → indexes).

### 1.1 Vertical Slice Trace

1. **Controller**: HTTP method, path, request body type, `@RequestHeader` idempotency fields.
2. **Service**: `findByIdempotencyKey`/equivalent lookup, found-vs-not-found branching, transaction boundaries.
3. **Repository**: Dedup queries; note unique/compound indexes.
4. **Entity/Document**: Idempotency key fields; `@Indexed(unique=true)`, `@CompoundIndex`, SQL `UNIQUE`.
5. **Kafka consumers**: `@KafkaListener` — idempotency check on `eventId`/`messageKey` before processing?

### 1.2 Idempotency Checklist

> Checks #1 and #2: cross-reference Phase 0.5 canonical key. Mismatch → score under #1 with canonical key as fix.

| # | Check | What to verify |
|---|-------|----------------|
| 1 | **Key scope** | Uniqueness is compound (`idempotencyKey + memberId + tenantId`), not global-only. Fields must match Phase 0.5 canonical key. |
| 2 | **Replay semantics** | Same key + same payload → same outcome; no duplicate DB rows/events/external calls. |
| 3 | **Payload mismatch** | Same key + different critical field → explicit error (409 or domain error), not silent corruption. |
| 4 | **Read–modify–write race** | Concurrent duplicates: unique DB index or atomic op enforces single winner. Catch `DuplicateKeyException`/`DataIntegrityViolationException` → re-fetch existing record by dedup key and return it — not null, not 500. |
| 5 | **Atomic operations** | For counters/balances: prefer `findAndModify`/`@Version`/`UPDATE … WHERE …` over read-then-write. `@Version`: catch `OptimisticLockingFailureException` → 409 or retry, never 500. |
| 6 | **Partial failure** | DB + Kafka + HTTP: double publish on retry? Prefer outbox or record completion before irreversible calls. |
| 7 | **Kafka key** | Producer uses business key (`userId`, `orderId`) as Kafka message key for ordered, idempotent consumption. |
| 8 | **Redis avoidance** | Idempotency state must NOT rely solely on Redis (eviction = lost state); DB unique index is source of truth. |
| 9 | **Null / empty key** | Controller or service validates key is present when required; defined behavior when key is optional. |
| 10 | **Retry safety on external calls** | Auto-retry on non-idempotent external calls (payments, order placement) is forbidden. Downstream must itself be idempotent if retried. |
| 11 | **Replay path side effect completeness** | Found-existing/early-return path must not silently skip: Kafka events, audit log entries, webhook triggers, cache invalidations. |
| 12 | **AOP self-invocation on transaction boundary** | Dedup check + mutation split across two methods in same class, `@Transactional` only on inner → Spring AOP bypasses transaction; check and write no longer atomic. |
| 13 | **DB commit before Kafka publish** | Publishing inside `@Transactional` on non-transactional producer fires message even if DB rolls back — ghost event. Use outbox or `TransactionSynchronizationAdapter.afterCommit()`. |
| 14 | **Unique index on existing data** | Adding unique index to collection with historical duplicates will fail. Verify: (a) dedup query run first, (b) Mongock `@ChangeUnit` is check-before-create. |
| 15 | **IDOR on idempotency key scope** | Key lookup scoped to key only — without `memberId`/`tenantId` — lets any user replay another's operation. Scope must include ownership dimension from JWT, not request body. |
| 16 | **Isolation level for read-modify-write** | Read-then-check without unique index: verify `@Transactional(isolation = Isolation.REPEATABLE_READ)` or pessimistic locking. `READ_COMMITTED` allows concurrent "not found" → both write → duplicates. |
| 17 | **Replay response consistency** | On found-existing path, return same HTTP status code and body as original — reconstruct from existing record. Different status (200 vs 201) or null body breaks client retry logic. |
| 18 | **Idempotency TTL anti-pattern** | `expireAfterSeconds` TTL index or scheduled purge as sole dedup mechanism = **RISK**. TTL expiry silently allows re-processing. Replace with a **unique compound index** (ESR order: equality by cardinality → sort → range) — DB enforces uniqueness permanently with no expiry window. Produce ESR index recommendation in action items. |
| 19 | **@Scheduled mutation idempotency** | `@Scheduled` state mutations must: (a) acquire distributed lock (ShedLock `@SchedulerLock`, DB advisory lock, or `findAndModify` on job-lock record) — prevents concurrent pod execution; (b) status-check before mutating — safe on restart/retry. |
| 20 | **Kafka consumer offset commit safety** | `@KafkaListener` state mutations must use manual ack (`AckMode.MANUAL`/`MANUAL_IMMEDIATE`). Call `Acknowledgment.acknowledge()` only after all side effects succeed. Auto-commit: crash before DB write → silent loss; crash after DB but before downstream → offset committed with incomplete state. |

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
IDEM-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Prepend `### Project Idempotency Pattern (discovered)` block (Phase 0.5 Step D) before findings.

Per state-mutating endpoint/consumer, one trace line:
`trace: {endpoint or consumer} | dedup={yes/no} | query={repo method or none} | unique_index={fields or none}`

covers_dedup_key = NO or UNKNOWN → include this block once:

> **Recommended index fields** (from Phase 0.5 canonical key / project field scan):
> `[f1, f2, f3]` — source: `<established | inferred — sibling repos | inferred — project scan | UNKNOWN — ask team>`
>
> No unique compound index covers these fields on `<EntityName>` — neither entity annotations nor migration files.
> Confirm with team whether DB-level constraint exists outside this diff. If not, add:
>
> ```js
> // MongoDB — ESR order: equality (high-cardinality first) → sort → range
> db.<collection>.createIndex(
>   { f1: 1, f2: 1, f3: 1 },
>   { unique: true, name: "idx_<collection>_<f1>_<f2>_<f3>" }
> )
> ```
> ```sql
> -- MySQL / PostgreSQL
> CREATE UNIQUE INDEX idx_<table>_<f1>_<f2>_<f3> ON <table> (f1 ASC, f2 ASC, f3 ASC);
> ```

Last line — checks summary over: checklist #1–#20 (list check numbers).
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `IDEM: no findings.` + checks summary.

---

## Constraints

- **Before/after code required**: Every action item must include verbatim Before and After blocks.
- **Read before commenting**: Read actual file before making finding.
- **Phase 0.5 token budget**: 1 grep (C1) + 1 grep (E1, only if entity index not in Section 4 diff) + 1 grep (E2.5, only if covers_dedup_key ≠ YES after E2) + 1 grep (E4, only if canonical key = UNKNOWN and E2.5 = NO). ≤ 2 repo files (C3, only if C2 ambiguous). Never scan service files.
- **No hardcoded domain field names**: Phase 0.5 uses structural heuristics only.
- **Pattern inference, not proof**: Note source (`established` vs `inferred`).
- **Reactive awareness**: `Mono<T>`/`Flux<T>` are first-class. Transaction boundaries use `ReactiveMongoTransactionManager` — not standard `@Transactional`.
- **Redis TTL is not idempotency**: DB unique index is source of truth.
- **Kafka consumers**: `@KafkaListener` mutating state = same risk as HTTP endpoints.
- **AOP self-invocation is a silent bug**: `@Transactional` on inner method called from same class does nothing at runtime.
- **Replay path is not free**: Required side effects (Kafka, audit, cache) must be reproduced or documented as intentionally skipped.
- **IDOR on key scope**: Ownership dimension from JWT — never request body alone.
- **Migration idempotency**: `@ChangeUnit` and SQL changesets creating unique indexes must verify no existing duplicates; changeset must be retryable.
- **TTL anti-pattern → unique index (ESR)**: Check #18 fires → never suggest TTL fix. Produce ESR compound index recommendation: equality (high-cardinality first) → sort → range.
- **ESR for all index suggestions**: Equality (high-cardinality first) → Sort → Range. Never place range fields before sort.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
