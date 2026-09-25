---
name: spring-review-api-docs
description: Reviews API documentation staleness. Detects doc-triggering changes (new/removed endpoints, field changes, error codes, Kafka events, auth changes) and checks docs/api/*.md against git log.
---

# Spring Review — API Documentation Check

## Model Guidance

Fast-tier. First output line: `[spring-review-api-docs] running on: {model} (fast-tier)`
No escalation — all checks are mechanical (pattern detection + git log date comparison). No reasoning-tier consultation.

---

## Phase 0 — Change Set

Diff slice provided in prompt → use it, skip cache. Read `docs/api/*.md` from disk and run `git log` as needed.

Else read `.review-context.md`. Validate: first line = `<!-- review-context: <hash> -->`. Absent/stale → stop: "Run `review-context` first."

Focus on:
- Controllers: `*Controller.java`, `*Router.java`, `*Handler.java`
- DTOs: `*Request.java`, `*Response.java`, `*Dto.java`
- API docs: `docs/api/*.md`

---

## Phase 5 — API Documentation Check

### 5.1 Detect Doc-Triggering Changes

Changes that **REQUIRE** documentation update:
- New or removed endpoint
- New, removed, or renamed request/response field
- Changed field type, validation constraint, or optionality
- New or removed HTTP error code/business error code
- New Kafka event published or consumed
- Changed authentication/authorization requirement
- Changed idempotency strategy

### 5.2 Locate Doc File

Convention: `docs/api/<ControllerName>.md`

### 5.3 Freshness Check

1. Read `docs/api/<ControllerName>.md` (if exists).
2. Compare "Last Updated" date and "Source Commit" against `git log` for controller and service files.
3. If doc stale OR doc-triggering change detected but doc not updated:

```
API DOC ACTION REQUIRED: <ControllerName>.md
  Triggered by: <field added/removed, error code changed, etc.>
  Doc status: MISSING | STALE (last commit: <hash>, doc shows: <hash>)
  Action: Update docs/api/<ControllerName>.md to reflect the change.
```

4. If doc current or no doc-triggering change:

```
API DOC: OK — <ControllerName>.md is current.
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
AD-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Per current doc, one line: `AD ok: docs/api/{Controller}.md current`

Last line — checks summary over: `doc_triggering_changes, doc_freshness`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `AD: no findings.` + checks summary.

---

## Constraints

- **API doc scope**: Only flag when contract-visible change present. Internal refactors don't require doc updates.
- **Read doc file**: Always read existing doc file (if present) before reporting stale.
- **Check git log**: Use `git log` to determine when controller last changed vs. when doc last updated.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
