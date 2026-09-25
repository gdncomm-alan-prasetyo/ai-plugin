---
name: spring-review-integration-tests
description: Reviews integration test quality. Checks build correctness, positive/negative balance, test logic validity, business logic coverage, and assertion integrity (gamed assertions are P0). Integration tests only — @SpringBootTest, @WebFluxTest.
---

# Spring Review — Integration Test Quality & Coverage

## Model Guidance

Capable-tier. First output line: `[spring-review-integration-tests] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- **Phase 5 (assertion value integrity)**: a changed test assertion value is plausible on the surface but cannot be independently derived from the production code change alone — you cannot confidently classify it as CORRECT vs GAMED. Ask Opus for a definitive verdict. This is the highest-value escalation trigger in this skill.
- A complex business formula change (compound multipliers, graduated tiers, multi-step rounding) makes it genuinely unclear what the mathematically correct expected test value should be — and the wrong verdict here means a gamed assertion ships undetected

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
Verdict enum for this skill: `CORRECT | GAMED | SUSPICIOUS` — REASON must show derivation of correct expected value. CORRECT returned → classify assertion OK.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Split changed files:
- **Group A — Production** (`src/main/**`): need test coverage.
- **Group B — Test** (`src/test/**`): need build and logic review.

Process Group B (Phase 1) → then Group A (Phases 2, 10).

Section 5 contains test metadata only (annotation, base class, method names) — not full content. Read test files directly from disk via Read tool.

---

## Phase 1 — Test Build & Structure

> Read every new/modified test file in Group B fully before any finding.

### 1.1 Annotation Correctness

| Check | What to verify |
|-------|---------------|
| **Class-level annotation** | Must have `@SpringBootTest`, `@WebFluxTest`, `@WebMvcTest`, or project's base integration test annotation. `@ExtendWith(MockitoExtension.class)` alone is NOT acceptable. |
| **Base class** | Extends project's `BaseIntegrationTest` / `AbstractIntegrationTest` if one exists — missing base class means DB wipe, bean context, auth tokens may be absent. |
| **@ActiveProfiles** | Correct test profile applied if project uses profiles for test config. |
| **@AutoConfigureMockMvc / @AutoConfigureWebTestClient** | Present when test uses `MockMvc` or `WebTestClient` without full embedded server. |
| **@Transactional on test class** | Flag if present — rolls back after each test, hides Kafka, async, and Redis side-effects. Only acceptable when explicitly needed for rollback isolation. |

### 1.2 Test Method Structure

Per `@Test` method in changed test file:

| Check | What to verify |
|-------|---------------|
| **Arrange** | Test data set up before call (DB inserts, mock stubs, auth token). |
| **Act** | Exactly one call to system under test per method (one HTTP call, one Kafka message, one job invocation). |
| **Assert** | At least one assertion on response AND at least one on side-effects (DB state, Kafka message, Redis key, external stub call count). HTTP status alone is NOT sufficient. |
| **No business logic in tests** | Tests must not replicate business logic to compute expected values — use literals or pre-computed constants. |
| **No `Thread.sleep()`** | Async waits must use `Awaitility` or project's standard async wait helper. |
| **No shared mutable state** | Methods must not depend on execution order; each sets up its own data. |

```
TEST BUILD ISSUE: <TestClass#testMethod>
  Issue type: <missing annotation / wrong base class / missing assertion / shared state / Thread.sleep / etc.>
  Location: <file:line>
  Problem: <what is wrong>
  Fix: <what it should look like>
```

### 1.3 Context Load Risk

Patterns that cause `ApplicationContext` load failures:
- Missing `@MockBean` for external dependencies (Feign clients, `WebClient` beans) — if real bean requires running external service, must be mocked or disabled.
- `@Autowired` field not found in context — verify bean exists.
- Conflicting bean definitions from new `@TestConfiguration` class.
- Kafka listener auto-start not disabled in test properties — consumers must not auto-connect to real broker unless test Kafka container configured.

```
CONTEXT LOAD RISK: <TestClass>
  Risk: <missing @MockBean / unresolvable bean / Kafka auto-start / etc.>
  Location: <file:line>
  Fix: <how to resolve>
```

---

## Phase 2 — Positive & Negative Case Balance

Per changed endpoint, consumer, or method in Group A, verify corresponding integration tests cover both positive and negative scenarios.

### 2.1 Positive Cases

| Scenario | Expected assertion |
|----------|--------------------|
| **Happy path — standard input** | HTTP 2xx; DB row created/updated with correct fields; Kafka event published with correct payload; response body matches contract. |
| **Happy path — optional fields absent** | All optional fields omitted → succeeds with correct default behavior. |
| **Happy path — boundary value** | Input at exact boundary (e.g. `amount=0`, `size=maxAllowed`, `date=today`) → succeeds. |
| **Idempotency replay** | Second call with same key → same result; no duplicate DB rows; no duplicate Kafka events. |

### 2.2 Negative Cases

| Scenario | Expected assertion |
|----------|--------------------|
| **Missing required field** | `@NotNull`/`@NotBlank` field absent → HTTP 400 with correct field error. |
| **Invalid field format** | Wrong type, out-of-range, pattern mismatch → HTTP 400 with correct field error. |
| **Business rule rejection** | Domain precondition not met → correct business error code. |
| **Idempotency conflict** | Same key, different payload → correct conflict error code. |
| **Unauthenticated** | No token → HTTP 401. |
| **Wrong role** | Valid token, insufficient role → HTTP 403. |
| **Resource not found** | Non-existent ID → HTTP 404 or correct business error. |
| **Concurrent duplicate** | Concurrent duplicate requests → one persisted; second gets conflict or idempotent response (high-risk flows only). |

### 2.3 Balance Gap Reporting

```
MISSING POSITIVE CASE: <ClassName#methodName>
  Scenario: <which positive scenario is absent>
  Suggested test: <TestClass#suggestedMethodName>
  Assertions needed: <response + DB/Kafka/Redis>

MISSING NEGATIVE CASE: <ClassName#methodName>
  Scenario: <which negative scenario is absent>
  Suggested test: <TestClass#suggestedMethodName>
  Assertions needed: <error code, HTTP status, DB unchanged>
```

---

## Phase 3 — Test Logic Validity

> Verify tests exercise changed code paths — not just that a test exists.

Per integration test covering a changed method:

### 3.1 Does the test reach the changed code?

1. Read test method fully.
2. Trace call path: HTTP → Controller → Service → Repository (or Kafka → Consumer → Service).
3. Verify test input triggers the specific branch that changed.

| Failure pattern | Example |
|-----------------|---------|
| **Wrong input** | Changed branch handles `type="PREMIUM"` but test sends `type="BASIC"` — changed code never executes. |
| **Mocks changed method** | `@MockBean ServiceImpl` stubs the changed method — changed logic never called. |
| **Wrong endpoint** | Test calls `/v1/foo` but change is in `/v2/foo`. |
| **Shortcut path** | Changed code is in `else` branch, test input always enters `if`. |
| **Guard clause bypassed** | New eligibility check added, test data pre-seeded to always pass — rejection path never tested. |

```
TEST LOGIC GAP: <TestClass#testMethod> does not exercise <ClassName#method> (branch: <describe>)
  Reason: <why test misses changed code>
  Test input used: <request/message/trigger>
  Branch that changed: <file:line — what the change does>
  Fix: <what input/scenario needed to hit changed branch>
```

### 3.2 Are assertions meaningful?

Per `@Test` method covering changed path:
- **HTTP status only** — asserting `status().isOk()` without checking response body or DB state is insufficient.
- **Response body field missing** — new field added to response must be asserted.
- **DB state not verified** — mutating operations must verify the DB write.
- **Kafka event not verified** — if changed code publishes Kafka, test must consume and assert payload.
- **Redis state not verified** — if changed code writes/evicts cache key, test must verify Redis after call.
- **Side-effect count not verified** — if external HTTP call should happen exactly once, WireMock stub count must be asserted.

```
WEAK ASSERTION: <TestClass#testMethod>
  Missing assertion: <what is not being asserted>
  Affected change: <file:line>
  Fix: <what assertion to add>
```

---

## Phase 4 — Business Logic Coverage

> Verify tests validate actual business rules — outcome matches intended behaviour per changed rule, not just path reached.

### 4.1 Identify Changed/Affected Business Rules

Read production code diff carefully; list every changed/touched business rule:

| Rule type | Examples |
|-----------|---------|
| **Calculation / formula** | Points multiplier changed, fee percentage adjusted, rounding mode changed |
| **Eligibility condition** | New tier check, status filter changed, date range guard modified |
| **State transition** | Order flow changed, new intermediate state, transition guard removed |
| **Limit / cap / threshold** | Max retry count, daily limit, minimum amount |
| **Conditional branch** | New `if` block, existing condition changed, `else` path added |
| **Business error code** | New domain exception, existing error code swapped, HTTP status changed |
| **Side-effect rule** | Kafka event published under different conditions, cache evicted on new path |

### 4.2 Map Each Rule to Test Assertion

Per business rule from 4.1, find integration test verifying it:
1. Read test assertion validating this rule.
2. Verify assertion checks **outcome of the rule** — not just HTTP call succeeded.
3. Verify test exercises the **exact condition** the rule is about.

Per rule, answer:
- Test triggers this rule? (structural coverage)
- Assertion verifies rule's output — correct computed value, error code, DB state? (outcome coverage)
- Test covers both **passing side** and **failing side**?

### 4.3 Business Logic Coverage Gap Reporting

```
BUSINESS LOGIC NOT COVERED: <rule description>
  Production code: <file:line>
  Rule: <plain language>
  Missing test side: <passing / failing / both>
  Consequence: <what goes undetected>
  Suggested test: <TestClass#suggestedMethodName>
  Assertion needed: <exact value / error code / DB field>
  Priority: P0 — Must fix before merge
```

**Any uncovered business rule change is P0.** Changed rule with no test assertion = silent regression.

### 4.4 Existing Business Logic Broken by Change

Cross-check changed code against existing tests covering **unchanged** rules on same code path.

Per existing test covering a touched method:
1. Re-read test's scenario and assertion.
2. Trace through **new** production code with test's input.
3. Verify existing assertion still holds.

If existing test would now fail:

```
EXISTING BUSINESS LOGIC BROKEN: <TestClass#testMethod>
  Existing rule tested: <what business rule this verifies>
  Production change: <file:line>
  How it breaks: <why assertion no longer holds>
  Old expected value: <what test currently asserts>
  New actual value: <what changed code would now produce>
  Priority: P0 — Must fix before merge. Revert production change or update both
            production code and test with correct expected value confirmed against business requirement.
```

---

## Phase 5 — Assertion Value Integrity

> Catches test gaming — expected values changed to go green instead of fixing production code.

### 5.1 Find All Assertion Value Changes

From diff, locate every line in test files where assertion value changed. Look for changes to:
- `.isEqualTo(...)` / `.isEqualByComparingTo(...)`
- `.hasFieldOrPropertyWithValue("field", ...)`
- `jsonPath("$.field").value(...)`
- `.value(...)` in `WebTestClient` assertions
- `assertThat(...).isEqualTo(...)` / `assertEquals(expected, actual)`
- Expected error codes: `jsonPath("$.errorCode").value(...)` changes
- Expected HTTP status changes: `.isOk()` → `.isBadRequest()` etc.
- **Weakened assertions**: `.isEqualTo(specificValue)` → `.isNotNull()` or `.isGreaterThan(0)` — always suspicious
- **Assertions removed or deleted**

### 5.2 Verify Each Changed Assertion Against Business Rule

Per changed assertion from 5.1:

1. Read corresponding production code change.
2. Derive correct expected value from business rule (formula: compute manually; error code: match exception thrown; HTTP status: verify controller returns it; field value: verify DB/response).
3. Compare derived value against what test now asserts.
4. Classify:

| Classification | Condition | Priority |
|---------------|-----------|----------|
| **CORRECT** | Changed assertion matches what updated production code correctly produces per business rule | OK |
| **SUSPICIOUS** | Changed assertion plausible but cannot be derived directly from production change alone — needs business requirement reference | P1 |
| **GAMED ASSERTION** | Changed assertion doesn't match what production code should produce per business rule, OR assertion weakened to always pass | **P0** |

### 5.3 Gaming Patterns

| Pattern | How to detect | Classification |
|---------|--------------|---------------|
| **Value adjusted to match wrong output** | Formula `×2`→`×1` but test changed from `200` to `150` for `amount=100` — neither `200` nor `100` | GAMED |
| **Assertion weakened** | `.isEqualTo(100)` → `.isNotNull()`, or `.isEqualTo("POINT_INSUFFICIENT")` → `.is2xxSuccessful()` | GAMED |
| **Assertion removed** | `verify(...)` or `assertThat(...)` line deleted without replacement | GAMED |
| **Wrong error code** | Production throws `BALANCE_LOCKED` but test asserts `GENERAL_ERROR` | GAMED |
| **DB assertion removed** | Test previously queried DB to verify row created; assertion deleted | GAMED |
| **Expected count changed without matching logic** | `count=1` changed to `count=0` without production code change preventing insert | GAMED |
| **Correct value change** | `amount*0.1` → `amount*0.05`; test changed from `10` to `5` for `amount=100` — mathematically consistent | CORRECT |

### 5.4 Assertion Integrity Report

```
ASSERTION INTEGRITY VIOLATION — P0: <TestClass#testMethod>
  Location: <file:line>
  Before: <old assertion value>
  After: <new assertion value>
  Business rule: <what rule actually says — derived from production code>
  Correct expected value: <what assertion SHOULD be per business rule>
  Problem: <why wrong — gamed, weakened, or unsupported>
  Action: Developer must confirm correct expected value against business requirement
          and restore meaningful assertion before merge.
          Do NOT merge with gamed assertion — masks silent regression.
  Priority: P0 — Must fix before merge
```

```
ASSERTION NEEDS JUSTIFICATION — P1: <TestClass#testMethod>
  Location: <file:line>
  Changed assertion: <old> → <new>
  Why suspicious: <cannot derive from production change alone>
  Action: Developer must provide business requirement or ticket justifying this change.
  Priority: P1 — Confirm before merge
```

---

## Phase 10 — Structural Coverage

> **Minimum required coverage: ≥ 93%** (integration tests only).

### 10.1 New / Changed Code Paths

Per changed file in Group A:
- New methods added
- Existing methods with changed logic branches (new `if`, `switch`, `try/catch`, `flatMap`, reactive operator)
- Deleted methods (verify no dead test code references deleted method)

### 10.2 Map Code Paths to Integration Tests

Per new/changed code path:
1. Search `src/test` for integration tests exercising changed method.
2. Read each candidate test to confirm it reaches changed branch (see Phase 3.1).

### 10.3 Coverage Gap Detection

Coverage gap when:
- New method has no integration test calling it (directly or transitively).
- New `if`/`else` branch has no test exercising `else` (or `false`) path.
- New exception catch block has no test triggering exception.
- New Kafka consumer handler has no test publishing message and verifying handler runs.
- New scheduled/cron method has no test invoking it directly.

```
COVERAGE GAP: <ClassName#methodName> (branch: <happy/error/edge case>)
  Missing scenario: <description>
  Suggested test class: <ExistingIntegrationTestClass or NewIntegrationTestClass>
  Test method name: <descriptive name>
  Assertions needed:
    - <assertion 1 — response>
    - <assertion 2 — DB / Kafka / Redis state>
```

### 10.4 Coverage Threshold Warning

```
COVERAGE WARNING: Estimated coverage may fall below 93%
  Uncovered new paths: <count>
  Affected classes: <list>
  Required action: Add integration tests for gaps listed above before merging.
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
IT-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Per changed endpoint/consumer, one coverage line (scenarios per Phase 2 tables):
`IT coverage {endpoint}: pos {covered}/{applicable}, neg {covered}/{applicable}`

Per changed assertion (Phase 5): GAMED/SUSPICIOUS → finding with old value, new value, derived correct value. CORRECT → one line `assertion-ok: {TestClass#method:line} {old}→{new}`.

Last line — checks summary over: `build_structure, case_balance, logic_validity, business_coverage, assertion_integrity, structural_coverage`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `IT: no findings.` + checks summary.

---

## Constraints

- **Integration tests only**: No unit tests. All scenarios must be `@SpringBootTest` or `@WebFluxTest`.
- **Coverage threshold**: Minimum 93%.
- **Read before commenting**: Always read full test file and production file before any finding.
- **Structural analysis only**: Cannot run live coverage tools — treat gaps as pre-flight checklist. Verify with `mvn verify` + JaCoCo.
- **Both positive and negative cases mandatory**: Happy-path-only test suite is always a coverage gap.
- **Assertions must verify side-effects**: HTTP status alone never sufficient for mutating operation. DB, Kafka, Redis must be asserted.
- **Logic gaps matter as much as structural gaps**: Test with wrong input or mocking the changed method = no test.
- **Every changed business rule needs assertion — P0**: Changed formula, condition, error code, or state transition with no test = silent regression.
- **Gamed assertions are P0 — block merge**: Changed to match wrong output, weakened, or removed entirely — must fix before merge.
- **Derive expected values from business rule**: Compute independently. Agreement on wrong value doesn't mean correct.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
