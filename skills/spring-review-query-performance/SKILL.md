---
name: spring-review-query-performance
description: Reviews query performance and index coverage. Identifies new/changed queries, checks for missing indexes, full scans, N+1, unbounded queries, sort-without-index, and reactive blocking. Applies ESR (Equality→Sort→Range) to recommend optimal compound indexes.
---

# Spring Review — Query Performance & Index Analysis

## Model Guidance

Capable-tier. First output line: `[spring-review-query-performance] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- An aggregation pipeline uses non-standard operators (`$lookup`, `$graphLookup`, `$facet`, `$unionWith`) where ESR does not cleanly apply and the optimal index strategy is genuinely unclear
- The cardinality of a field is non-obvious from the code (no domain naming hints) and the ESR field-order recommendation depends on getting it right — a wrong order would make the index nearly useless

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Focus on:
- Repositories: `*Repository.java`, `*RepositoryImpl.java`, `*CustomRepository.java`
- Services with direct template usage: files using `mongoTemplate`, `jdbcTemplate`, `r2dbcEntityTemplate`
- Migrations: `*.json`, `*.sql`, `*.yaml`, `@ChangeUnit` classes
- Entity/document classes: `*Entity.java`, `*Document.java` — scan for `@Indexed`, `@CompoundIndex`, `@Index`

---

## Phase 1 — Identify New or Changed Queries

Per changed repository method or custom query, locate:
- `@Query` annotations (Spring Data)
- Spring Data derived method names (e.g., `findByUserIdAndStatus`)
- `mongoTemplate.find(Query, ...)` / `mongoTemplate.aggregate(...)`
- `jdbcTemplate.query(...)` / JPQL / native SQL
- Reactive: `ReactiveMongoTemplate`, `R2dbcEntityTemplate`

Read the **full query expression** — do not infer from method name alone.

Per query, extract and record:

| Field group | What to capture |
|-------------|----------------|
| **Equality fields** | Fields compared with `=`, `.is()`, `.in()`. List in order of decreasing cardinality. |
| **Sort fields** | Fields in `ORDER BY`, `.sort()`, `Sort.by()`. Preserve sort direction (ASC/DESC). |
| **Range fields** | Fields compared with `>`, `<`, `>=`, `<=`, `BETWEEN`, `.gt()`, `.lt()`, `.gte()`, `.lte()`, `$regex`. |
| **Projection fields** | Fields fetched via `.include()`/`SELECT` — used to evaluate covered-index eligibility. |

---

## Phase 2 — Discover Declared Indexes

Scan `.review-context.md` for all index declarations in:

1. **Entity/Document annotations**
   - `@Indexed` on field → single-field index.
   - `@CompoundIndex(def = "{'field1': 1, 'field2': -1}")` on class → compound index.
   - `@Index` (Spring Data JDBC/JPA).

2. **Migration files** (MIGRATION category in change set):
   - MongoDB Mongock/Liquibase Mongo changesets calling `createIndex`.
   - SQL `CREATE INDEX`/`ALTER TABLE ... ADD INDEX`.
   - Extract: collection/table name, field list, field order, direction.

3. **Repository `@Query` hints**: `{ $hint: { ... } }`.

Produce **Declared Index Registry** per collection/table:

```
collection: <name>
  idx_1: { field1: 1 }
  idx_2: { field1: 1, field2: -1, field3: 1 }
```

If no index declarations found, record as `indexes: UNKNOWN — verify manually with db.<collection>.getIndexes()`.

---

## Phase 3 — Index Field Sequence Analysis (ESR Rule)

Per query identified in Phase 1, determine optimal compound index field order using **ESR rule**:

```
Optimal Index Field Order:
  1. Equality fields   (highest cardinality first → narrows result set fastest)
  2. Sort fields       (match sort order → avoids in-memory sort)
  3. Range fields      (last → range predicate limits index scan to prefix)
```

### Cardinality ranking for Equality fields

| Cardinality | Examples |
|-------------|---------|
| Very high | `userId`, `orderId`, `transactionId`, `email` |
| High | `sessionId`, `requestId`, `externalRef` |
| Medium | `createdDate` (date only), `category`, `country` |
| Low | `status` (ACTIVE/INACTIVE), `type` (enum), `isDeleted` (boolean) |
| Very low | boolean flags |

Always put **high-cardinality equality fields before low-cardinality**.

### ESR example

```
Query: filter by status='ACTIVE' AND userId=? AND createdAt > '2024-01-01' ORDER BY createdAt DESC

Equality : userId (very high), status (low)
Sort     : createdAt DESC
Range    : createdAt > '2024-01-01'

Note: createdAt appears in both Sort and Range. Sort takes precedence.

Optimal index: { userId: 1, status: 1, createdAt: -1 }
```

Produce one ESR breakdown per query:

```
query: <file:line> — <methodName>
  equality : <field1 (high-card)>, <field2 (low-card)>, ...
  sort     : <sortField ASC/DESC>, ...
  range    : <rangeField op>, ...
  esr_index: { field1: 1, field2: 1, sortField: -1, rangeField: 1 }
  note     : "<any cardinality assumption or caveat>"
```

---

## Phase 4 — Index Coverage Check

Per query and its ESR-recommended index (Phase 3), compare against Declared Index Registry (Phase 2).

### Coverage rules

Existing index **covers** query if:
1. **Prefix match**: starts with all equality fields (commutative for equality) AND includes sort fields in correct direction AND includes range fields.
2. **Direction match**: for sort fields, direction must match OR index is fully reversible. Mixed directions require separate index.
3. **No missing fields**: every field in filter and sort must appear in index.

### Coverage outcomes

| Outcome | Meaning |
|---------|---------|
| `COVERED` | Existing index fully covers query. |
| `PARTIALLY COVERED` | Existing index covers some but not all filter/sort fields — partial scan + in-memory filter. |
| `NOT COVERED` | No declared index covers query. Full collection/table scan. |
| `UNKNOWN` | No index declarations for this collection — manual verification required. |

`NOT COVERED` or `PARTIALLY COVERED` → produce New Index Recommendation (Phase 5).

---

## Phase 5 — New Index Recommendations

Per `NOT COVERED` or `PARTIALLY COVERED` query:

### MongoDB

```js
// Collection: <collectionName>
// Covers: <query method at file:line>
// ESR order: equality(<fields>) → sort(<fields>) → range(<fields>)
db.<collectionName>.createIndex(
  { <field1>: 1, <field2>: 1, <sortField>: -1, <rangeField>: 1 },
  { name: "idx_<collectionName>_<field1>_<field2>_<sortField>", background: true }
)
```

### MySQL / PostgreSQL

```sql
-- Table: <tableName>
-- Covers: <query method at file:line>
-- ESR order: equality(<fields>) → sort(<fields>) → range(<fields>)
CREATE INDEX idx_<tableName>_<field1>_<field2>_<sortField>
  ON <tableName> (<field1> ASC, <field2> ASC, <sortField> DESC, <rangeField> ASC);
```

### Migration reminder

```
ACTION REQUIRED: Add index via migration changeset, not directly in production.
  Mongock: new @ChangeUnit calling mongoTemplate.indexOps("<collection>").ensureIndex(...)
  Liquibase: new changeset with <createIndex> tag
```

---

## Phase 6 — Slow Query Checklist

| Risk | Indicators |
|------|-----------|
| **Full collection/table scan** | Filter field has no index; large collection + no limit. |
| **Sort without index** | `sort()` on non-indexed field causes in-memory sort (MongoDB: 32 MB limit). |
| **N+1 query** | Loop calling `findById()` per iteration instead of `findAllById()`. |
| **Unbounded query** | `findAll()` or equivalent with no `Pageable`/`LIMIT` on large dataset. |
| **Regex / `$where` / function index** | Cannot use standard B-tree indexes; full scan unless partial or text index exists. |
| **Blocking query in reactive chain** | Synchronous JDBC call inside `Mono.fromCallable` not offloaded to bounded scheduler. |
| **Low-cardinality leading field** | Index starts with boolean or status field — most documents match, index nearly useless. |
| **Covered-index miss on projection** | Fields in `SELECT`/`.include()` not in index — forces document fetch even when filter is indexed. |

```
QUERY PERFORMANCE RISK: <risk type>
  Location: <file:line>
  Query: <the query pattern>
  Risk: <why slow>
  Fix: <add index / add LIMIT / use findAllById / offload to boundedElastic>
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
QP-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Per COVERED query, one line: `covered: {file:line} {method} ← {index definition}`
Per NOT COVERED / PARTIALLY COVERED query: finding includes ESR breakdown block (Phase 3 format) + full index DDL (Phase 5 format) + migration reminder.
Registry UNKNOWN for a collection → state `indexes UNKNOWN — verify manually with db.{collection}.getIndexes()`.

Last line — checks summary over: `full_scan, sort_without_index, n_plus_1, unbounded_query, regex_where, blocking_in_reactive, low_cardinality_leading, covered_projection`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `QP: no findings.` + checks summary.

---

## Constraints

- **ESR is mandatory**: Every compound index must follow Equality → Sort → Range. Never put range fields before sort.
- **Cardinality drives equality order**: Put high-cardinality equality fields before low-cardinality. State cardinality assumption explicitly.
- **Read actual query**: Always read full `@Query` value or template expression — do not infer from method names.
- **Coverage requires all fields**: Index covering 3 of 4 filter fields is `PARTIALLY COVERED`. Flag it.
- **Direction matters for sort**: `{ createdAt: 1 }` does NOT cover `ORDER BY createdAt DESC` in compound sort context unless entire index is reversed.
- **Range field last**: Range predicate on field X means index cannot use fields after X for filtering. Always place range fields at end.
- **Unknown indexes are not safe**: No declarations → report `UNKNOWN`. Never assume covering index.
- **N+1 is a silent killer**: Loop calling repository per iteration — flag even if collection seems small.
- **Reactive blocking**: Synchronous repository call inside reactive chain without `Mono.fromCallable(...).subscribeOn(Schedulers.boundedElastic())` blocks event loop thread — always P0.
- **Migration required**: New index recommendations must use migration changeset (Mongock/Liquibase), not applied directly.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
