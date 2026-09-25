---
name: spring-review-business-logic
description: Reviews business logic integrity — old flow preservation, new logic correctness (conditions, calculations, state transitions, boundary cases, ordering), cross-flow interference, and invariant violations.
---

# Spring Review — Business Logic Integrity

## Model Guidance

Reasoning-tier. First output line: `[spring-review-business-logic] running on: {model} (reasoning-tier)`
No escalation — this IS the reasoning-tier. No further escalation.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

**Caller data**: Section 6 (`## 6. Caller Analysis`) already contains grep results for every changed service/repository method. Read from there — do not run additional grep or shell commands.

---

## Phase 15 — Business Logic Integrity

### 15.1 Understand Old Business Logic

From **Section 4** diff, read code **as it was before change** (`-` lines) for every modified service method. Need full body → read changed file from disk.

Per changed method, capture:
1. **What it did** — business operation performed.
2. **What conditions it checked** — guard clauses, eligibility, early returns, exception paths.
3. **What it returned/produced** — response shape, DB records, Kafka events.
4. **What callers depended on** — assumptions upstream callers made about output.

Document as **baseline contract** before the change.

### 15.2 Understand New Business Logic

Read changed code **as it is now** and capture same four points.

Identify exactly what changed:
- New conditions (new `if`, early return, new exception thrown)
- Conditions removed or weakened
- Calculation logic changed (formula, rounding, operator, field used)
- Execution order changed (step A now before step B)
- New side effects added (new DB write, Kafka event, external call)
- Side effects removed
- State transitions changed

### 15.3 Old Flow Preservation Check

Using **Section 4** diff (read full changed file from disk when method bodies needed), per **existing business flow** through any changed method, verify same correct outcome.

Existing flow is broken when:

| Scenario | Example |
|----------|---------|
| **New guard clause cuts valid old path** | New `if (request.getPartnerId() != null)` early-return but some old callers never set `partnerId` — they now get silent no-op. |
| **Condition inverted or tightened** | `if (balance >= amount)` → `if (balance > amount)` — zero-balance edge case now incorrectly rejects valid exact-match deduction. |
| **Execution order changed, different state** | Points recorded before eligibility check; now eligibility checked first — old flow that relied on record existing even on failure now finds no record. |
| **Shared method result changed** | Method returns calculated value used by multiple callers. Changing formula affects every caller. |
| **Early return swallows required side effect** | `return existingResult;` replay path skips Kafka publish or audit log that callers depend on. |
| **Eligibility/filter condition changed scope** | Query filter tightened (e.g. adding `AND status='ACTIVE'`) — previously eligible records now excluded. |

```
BUSINESS LOGIC BREAK: Old flow broken
  Method: <ClassName#methodName> at <file:line>
  Old behaviour: <what it did before>
  New behaviour: <what it does now>
  Affected flow: <which business scenario is now broken>
  Example: <concrete input that used to work and now fails or produces wrong output>
  Fix: <how to restore old behaviour while keeping new addition>
```

### 15.4 New Logic Correctness Check

| Category | What to check |
|----------|--------------|
| **Condition correctness** | Is `if` condition checking right field, right comparator (`>=` vs `>`), right value? |
| **Calculation correctness** | Formulas arithmetically correct? Operator precedence correct? Rounding at right step? Units consistent? |
| **State transition validity** | New state transition allowed by business rules? Code prevents invalid transitions? |
| **Boundary and edge cases** | `amount=0`, empty list, `date=today`, no prior history, balance exactly equals required amount? |
| **Operation ordering** | Irreversible operations (charge, deduct, publish) guarded by all required pre-checks? DB write committed before Kafka publish? |
| **Conditional completeness** | Every `if` has correct `else`? Every `switch` covers all relevant cases? |
| **Loop and aggregation correctness** | Accumulator initialized correctly? Empty collection handled? |
| **New feature flag / condition scope** | Gate correctly isolates new behaviour? `else` branch correctly preserves exact old behaviour? |

```
BUSINESS LOGIC ERROR: New logic is incorrect
  Method: <ClassName#methodName> at <file:line>
  Error type: <wrong condition / wrong calculation / invalid state transition / missing edge case / wrong ordering>
  Current code: <specific lines that are wrong>
  Problem: <what is wrong and why>
  Example: <input → actual output → expected output>
  Fix: <corrected logic>
```

### 15.5 Cross-Flow Interference Check

When change adds new behaviour conditionally activated, verify it does not interfere with other flows sharing same code path.

Steps:
1. List all callers and entry points from **Section 6** of `.review-context.md`.
2. Per caller, trace which branch of new conditional logic it will take.
3. Verify each caller reaches branch it is supposed to reach.

| Pattern | Example |
|---------|---------|
| **Flag-based routing gone wrong** | New `if (request.getChannel() == MOBILE)` but internal batch job calls this without setting `channel` — defaults to `null`, throws NPE or takes wrong path. |
| **Shared state mutation** | New logic writes field on entity that old logic also reads — old flow reads unexpected value. |
| **New Kafka event fires on old flows** | Kafka publish moved outside conditional — now fires for all flows including ones that should not trigger downstream event. |
| **Cache populated with wrong scope** | New `@Cacheable` caches result keyed by `memberId`, but same method called with different `channel` values — old callers get cached result computed for different channel. |

```
BUSINESS LOGIC INTERFERENCE: New logic bleeds into existing flow
  Method: <ClassName#methodName>
  New code: <file:line>
  Affected existing flow: <which other caller/path incorrectly affected>
  Problem: <how new logic changes behaviour for existing flow that should be unchanged>
  Fix: <how to isolate new logic>
```

### 15.6 Business Invariant Verification

Identify business invariants that must always hold (e.g. "member's total locked points must never exceed available balance").

Per invariant relevant to changed code, verify:
- Old code upheld it before change.
- New code continues to uphold it.
- No intermediate state where invariant is temporarily violated and could be observed by concurrent request.

```
BUSINESS INVARIANT RISK: <invariant description>
  Relevant code: <file:line>
  Risk: <how change could violate invariant>
  Scenario: <sequence of events leading to violation>
  Fix: <how to protect invariant>
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
BL-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Per changed method, one baseline line:
`baseline: {Class#method} | old={behaviour} | new={behaviour} | changed={conditions/calculations/ordering/side-effects}`

Every logic-error finding: `problem:` must include `example: input {X} → actual {Y} → expected {Z}`.

Last line — checks summary over: `old_flow, new_logic, cross_flow, invariants`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `BL: no findings.` + checks summary.

---

## Constraints

- **Read diff carefully**: Read before/after from Section 4. Do not skim or infer from method names.
- **Cache + targeted file reads**: Diffs in Section 4, caller data in Section 6. Read changed files from disk for full method bodies. No git commands or grep.
- **Concrete examples required**: Every logic error finding must include input → actual output → expected output.
- **Invariants are business rules**: Domain-specific — ask user about key invariants if not apparent from code.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
