---
name: spring-review-downstream-impact
description: Reviews downstream and caller impact when shared service/utility methods change. Checks return value, parameter, side-effect, exception, reactive contracts, and calculation logic propagation to all callers.
---

# Spring Review — Downstream / Caller Impact

## Model Guidance

Capable-tier. First output line: `[spring-review-downstream-impact] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- A calculation formula change (multiplier, rate, rounding, graduated tier) has complex mathematical implications where verifying correctness requires domain-level reasoning beyond what is derivable from the code alone, and the change propagates to 5+ callers with different usage patterns
- A reactive return-type change (`T` → `Mono<T>` or `Flux<T>`) cascades to 5+ callers and it is ambiguous whether all callers correctly handle the new async contract without blocking

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Focus on services, utilities, and domain classes. Per changed method, identify all callers.

---

## Phase 4 — Downstream / Caller Impact

### 4.1 Identify Shared Methods Changed

Per changed method in service or utility class, find all callers:

1. Check `.review-context.md` Section 6 (`## 6. Caller Analysis`) first — contains pre-populated grep results for changed service/repository methods. Use directly if method appears there.
2. Method not in Section 6 → run grep:
```
grep -r "<methodName>" src/main --include="*.java" -l
```

### 4.2 Impact Checklist per Caller

Per caller of changed method:

| Check | What to verify |
|-------|---------------|
| **Return value contract** | Return type, nullability, or semantics changed — all callers must handle. |
| **Parameter contract** | New required parameter added — default assumed by existing callers? |
| **Side-effect changes** | New DB write, Kafka event, or external API call — callers may trigger duplicates. |
| **Exception contract** | New checked/unchecked exception — callers not catching it surface unhandled error. |
| **Reactive contract** | Blocking ↔ reactive contract change (`Mono<T>`) — all callers must update. |
| **Multiplier / calculation logic** | Formula, rounding, or multiplier source changed — all downstream flows (display, charge, audit) must be validated. |

```
DOWNSTREAM IMPACT: <changedMethod> in <ClassName>
  Callers affected: <list of files:lines>
  Risk: <how change propagates>
  Recommended action: <fix or test to add>
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
DI-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Every finding lists affected callers — fold `callers: {file:line list}` into `problem:`.

Last line — checks summary over: `return_contract, parameter_contract, side_effects, exception_contract, reactive_contract, calculation_logic`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `DI: no findings.` + checks summary.

---

## Constraints

- **Section 6 first, grep as fallback**: Caller data pre-populated by be-review-context. Grep only if method absent from Section 6.
- **Calculation changes are high risk**: Formula/multiplier change propagates to every caller — flag all.
- **Reactive contract mismatches are P0**: `T` → `Mono<T>` breaks every caller expecting synchronous return.
- **Read before commenting**: Read actual callers before assessing impact.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
