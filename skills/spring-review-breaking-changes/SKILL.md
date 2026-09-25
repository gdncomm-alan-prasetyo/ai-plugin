---
name: spring-review-breaking-changes
description: Reviews breaking flow changes — validation tightening (@NotNull/@NotBlank, constraint changes, enum removals) and index/schema changes (new unique indexes, removed indexes, renamed fields) and their impact.
---

# Spring Review — Breaking Flow Changes

## Model Guidance

Capable-tier. First output line: `[spring-review-breaking-changes] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- An exception class hierarchy change spans 3+ levels of inheritance and it is unclear which `@ExceptionHandler` (matched by supertype) would catch the modified exception — the handler match determines whether callers silently receive a different HTTP status
- A try-catch re-throw pattern is ambiguous about what HTTP status callers will receive: the exception is re-wrapped or re-thrown in a way where the handler registry match is non-obvious

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Focus files: `*Request.java`, `*Response.java`, `*Dto.java`, `*Entity.java`, `*Document.java`, migrations (`*.json`/`*.sql`/`*.yaml`), `*.java` with `enum`, `*Controller.java`, `*Router.java`, `*Handler.java`, `*ControllerAdvice.java`, `*ExceptionHandler.java`, `*Exception.java`, `*ErrorHandler.java`, `*Service.java`, `*ServiceImpl.java`

---

## Phase 7 — Breaking Flow Changes

### 7.1 Validation Changes

| Change | Risk |
|--------|------|
| `@NotNull`/`@NotBlank` added | Existing null payloads → 400 |
| Constraint tightened (`@Size`, `@Pattern`) | Previously valid payloads rejected |
| Field removed from DTO | Silently ignored — flag for deprecation |
| Enum value removed | Old value → deserialization error |
| Business rule condition changed | Previously valid requests rejected |

### 7.2 Index / Schema Changes

| Change | Risk |
|--------|------|
| New unique index | Existing duplicates → index creation fails |
| Index removed | Queries become full scans |
| Index fields changed | Covered queries lose index |
| New non-null field added | Existing rows → NPE/validation fail |
| Field renamed | Reads return null until migration runs |

Per new unique index:
```
UNIQUE INDEX SAFETY CHECK: <collection/table>.<indexName>
  Fields: <field1, field2>
  Action: Run dedup query first.
  Sample: db.<col>.aggregate([{$group:{_id:{f1:"$f1",f2:"$f2"},count:{$sum:1}}},{$match:{count:{$gt:1}}}])
```

---

## Phase 7.3 — API Response & Endpoint Contract

### 7.3.1 Response DTO Field Changes

| Change | Risk |
|--------|------|
| Field removed | Callers → null/deserialization error |
| Field type changed | Callers → runtime blow-up |
| Field renamed | Old name → null; new name unknown to old callers |
| Nested object flattened/wrapped | Callers navigating nested path break |

```
RESPONSE CONTRACT BREAK: <ClassName>.<fieldName>
  Change: <removed/type X→Y/renamed X→Y>
  Action: Add new field alongside old, or version endpoint.
```

### 7.3.2 JSON Annotation Changes

Scan diff for `@JsonProperty`, `@JsonIgnore`, `@JsonInclude`, `@JsonAlias`, `@JsonUnwrapped`, `@JsonSerialize`, `@JsonDeserialize`.

| Change | Risk |
|--------|------|
| `@JsonIgnore` added | Field disappears from response |
| `@JsonProperty` removed/renamed | Wire name changes |
| `@JsonInclude(NON_NULL)` added | Null fields now absent |
| `@JsonUnwrapped` added/removed | Nesting structure changes |
| Custom serializer swapped | Output format changes |

```
JSON ANNOTATION BREAK: <ClassName>.<fieldName>
  Change: <annotation added/removed/changed>
  Wire before → after: <format change>
```

### 7.3.3 Endpoint Path, Method, and Status Code Changes

Scan `*Controller.java`/`*Router.java`/`*Handler.java` for `@*Mapping`, `ResponseEntity`, `HttpStatus` changes.

| Change | Risk |
|--------|------|
| Path changed | Old callers → 404 |
| HTTP method changed | Old callers → 405 |
| Endpoint deleted | All callers → 404 |
| Success status changed | Callers matching exact status/body break |
| Error status changed | Callers branching on error code route wrong |
| Path variable added/removed | URL structure breaks |
| Required query param added | Callers missing it → 400 |

```
ENDPOINT CONTRACT BREAK: <ControllerClass>.<methodName>
  Change: <path/method/status X→Y>
  Action: Add new endpoint alongside old, or version API.
```

---

## Phase 7.4 — Exception & Error Response Contract

### 7.4.0 Baseline — Read Existing Advice

Grep `@RestControllerAdvice|@ControllerAdvice` in `src/main`, read each file found. Record: error body shape (field names/types), all `@ExceptionHandler`-mapped exception types, HTTP status per handler. Use as baseline for all 7.4.x checks.

### 7.4.1 `@RestControllerAdvice` / `@ControllerAdvice` Changes

Scan any `@RestControllerAdvice`, `@ControllerAdvice`, or `ErrorController` class in diff.

| Change | Risk |
|--------|------|
| `@ExceptionHandler` added | Status changes from 500 — callers handling 500 miss it |
| `@ExceptionHandler` removed | Exception propagates differently |
| Handler status changed | Callers branching on that status break |
| Error body shape changed | Callers parsing error body break |
| Handler condition changed | Handler no longer fires for previously matched requests |

```
EXCEPTION HANDLER BREAK: <AdviceClass>.<handlerMethod>
  Exception: <ExceptionClass>
  Change: <status/body/handler changed>
  Action: Verify callers; update API docs.
```

### 7.4.2 Custom Exception Class Changes

| Change | Risk |
|--------|------|
| Exception class deleted | Throw sites fail to compile |
| Hierarchy changed | Supertype handler no longer catches it → different status |
| `@ResponseStatus` changed | All throw sites return different status |
| Message/fields changed | Error body changes if handler serializes fields |

```
EXCEPTION CLASS BREAK: <ExceptionClass>
  Change: <hierarchy/status annotation/field>
  Callers affected: <grep results>
  Action: Audit throw sites; update callers or add explicit handler.
```

### 7.4.3 try-catch Changes in Controllers and Services

Scan diff for added/removed/modified `try-catch` in `*Controller.java` and `*Service.java`.

| Change | Risk |
|--------|------|
| Exception swallowed | Error → silent success for callers |
| Catch type widened | More exceptions swallowed → status codes change |
| Catch type narrowed | Other exceptions now propagate as 500 |
| Re-throw changed | Original handler no longer fires → different status |
| New exception thrown | Callers that never saw error now receive error response |

```
TRY-CATCH CONTRACT CHANGE: <ClassName>.<methodName> at <file:line>
  Change: <swallowed/widened/re-throw→X>
  Risk: <callers get success/500/wrong status>
```

### 7.4.4 New Unhandled Exceptions in Controllers and Services

Scan diff in `*Controller.java`, `*Router.java`, `*Handler.java`, `*Service.java`, `*ServiceImpl.java` for new `throw` statements or `throws` clauses. Per new exception type, check advice baseline (7.4.0) for matching `@ExceptionHandler` (exact type or supertype). No match → unhandled → 500.

```
UNHANDLED EXCEPTION: <ExceptionClass> at <file:line>
  Handler found: NO
  Action: Add @ExceptionHandler, or throw an already-handled type.
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
BC-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `validation, index_schema, response_dto, json_annotations, endpoints, advice_handlers, exception_classes, try_catch, unhandled_exceptions`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `BC: no findings.` + checks summary.

---

## Constraints

- Read migration files before reporting risk.
- New unique index without dedup check → P0.
- `@NotNull` on previously optional field → always flag breaking.
- Enum removal → binary breaking.
- Response field removed/renamed → P1 minimum.
- `@JsonIgnore` on existing field → P0 if previously documented.
- Endpoint path/method change → P0.
- `@ExceptionHandler` removed → always check new propagation path.
- Swallowed exception → always flag.
- Exception hierarchy change → grep all throw sites first.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
