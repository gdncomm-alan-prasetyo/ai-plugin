---
name: generate-tests
description: >-
  Generate integration tests and unit tests for Spring Boot controllers and
  services. Use when asked to add, write, or generate tests for a controller,
  service, or based on code changes. Always scan project context, generate a
  plan, and get user approval before writing any code.
---

# Generate Tests (Integration & Unit)

## Announce Model

Print before any other output:
```
[generate-tests] Model: Sonnet | Phase: action (test generation)
```

When asked to "generate tests", "add tests", "write tests", or similar, follow this guide.

## Code patterns live in a reference file

This SKILL.md covers the **planning phase** only. Java templates (integration, unit, Kafka, WireMock, JSON fixtures) live in `references/test-patterns.md`. Read that file **once, at implementation time** — after the user approves the plan and you start writing code. Do not read it during planning; the planning steps below need none of it. Keeping templates out of the planning loop is deliberate: planning spans several turns of Q&A, and the templates would bloat every turn for no benefit.

## Agent behavior

- **Always follow the Planning Phase** before writing code. Do not skip to implementation.
- **Never plan and implement in the same response.** A response containing a plan must NOT contain any `Write`/`Edit` that creates/modifies test files. Stop after the plan, send it, wait. Approval = explicit phrase ("yes", "go ahead", "approve", "looks good", "do it"). Silence, a follow-up question, or a clarification is NOT approval.
- **Never assume test strategy.** Always ask Step 2 question 3 (A vs B) before drafting a plan. Do not pick a strategy from what feels reasonable, what the prior test did, or what other repo tests do. User picks.
- **Do not** run `mvn` or build commands unless the user explicitly asks.
- **Scope:** Generate test code only. Do not modify production logic.
- **Suggest** the exact Maven command for the user to verify; never run it.
- **Every test method needs ≥1 assertion.** A test with no assertion always passes regardless of behavior. A method that only calls `verify(...)` needs at minimum a response-code or DB-state assertion.

---

## Planning Phase (required before any code change)

### Step 0 — Determine scope and verdict (state conclusion FIRST)

Run before any plan output.

**Scope determination:**
- User named a file/class → scope = that file. Always.
- No file named, "tests for the changes" / "the bug fix" / "the recent commit" → scope = branch diff vs base.
- Ambiguous → skip to Step 2 question 1 and ask.

**Determine base branch and diff (run once):**
```bash
git rev-parse --abbrev-ref HEAD                 # current branch
git branch --list master main                   # pick base: master, else main
git diff {base}...HEAD --name-only              # files changed on this branch vs base
```
Use three-dot `{base}...HEAD` — it diffs the branch against its common ancestor, not just the last commit. (Plain `HEAD~1` only sees one commit and misses everything else on a multi-commit branch like a feature branch.) If no base branch exists (detached/standalone), fall back to `git diff HEAD --name-only` and tell the user you compared working tree only.

For each file in scope:
- File IS in the diff → `git diff {base}...HEAD -- {file}` to see exactly what changed. Focus gap analysis on changed methods/lines.
- File is NOT in the diff → no branch changes; analyze every method/branch (full coverage analysis).

**Quick triage (read each file at most once — Step 1 and Step 4 reuse these reads):**
1. Locate target class (Read).
2. Locate existing test files via Grep (`pattern: {ClassName}Test`, `path: src/test`, `glob: *.java`).
3. Read each existing test once; map its scenarios. Hold this in working memory for Steps 1 and 4.
4. Determine verdict.

**Output the verdict as the FIRST line of your reply**, before any plan or analysis:

> **Verdict: No new tests needed** — `{ClassName}` has {N} branches; all covered by `{ExistingTestClass}` ({existing methods covering them}). Stop here unless you want edge-case tests for SonarQube line-coverage padding.

OR

> **Verdict: Tests needed** — {N} of {M} branches uncovered: {brief list}. Proceeding to Planning Phase.

If "no new tests needed," do **NOT** continue. Wait for the user to accept or ask for padding tests.

### Step 1 — Scan project context

Read in parallel (skip anything already read in Step 0 — do not re-read):
1. `CLAUDE.md` at project root — tech stack, modules, domain model, Kafka topics, testing patterns, lessons learned. If it has a `<!-- repo-orientation:start -->` block, that covers stack/modules/entry points cheaper than rescanning `pom.xml`/`application.yml` yourself — read the rest of the file regardless, the block doesn't cover domain model, Kafka topics, or lessons learned.
2. Any `*architecture*.md` (glob `**/*architecture*.md`) — ADRs or integration notes not in `CLAUDE.md`.
3. `BaseIntegrationTest` (or equivalent base class) — available helpers, lifecycle hooks, shared utilities.
4. Target class — endpoints/methods, request/response types, dependencies. (Already read in Step 0 → reuse.)
5. Existing test class — already-covered scenarios. (Already read in Step 0 → reuse.) Check whether it can be extended rather than creating a new file.

### Step 2 — Ask uncertainties upfront (single block)

After scanning, present **all** open questions in one block before writing the plan:

> Before I write the plan, I need to clarify:
>
> **Scope**
> 1. **Source of changes** — tests for (a) a specific class/method, (b) a specific uncovered line/method, or (c) all branch changes vs base?
> 2. **Coverage target** — full coverage of the target class, or specific method(s)/line(s)?
>
> **Test strategy**
> 3. **Integration vs unit split** — choose one:
>    - (A) **Full integration coverage** — all scenarios (happy + negative) via `*ControllerIntegrationTest`
>    - (B) **Split** — happy flow via integration test, negative/exception flows via unit test (`*ControllerTest` or `*ServiceImplTest`)
>
> **Integration specifics** (if applicable)
> 4. **Kafka** — does this flow publish Kafka events to assert?
> 5. **External calls** — which Feign clients / HTTP calls? WireMock stubs already defined or need creating?
> 6. **Response JSON fixtures** — generate expected response JSON, or will you provide them?
>
> **Existing tests**
> 7. **Extend vs new file** — found existing test class `[XxxIntegrationTest]`. Add new methods, or create a separate class?

Wait for answers before writing the plan.

### Step 3 — Confirm scope from git (if user chose option c)

Scope already computed in Step 0 (`git diff {base}...HEAD --name-only`). Confirm staged/untracked too if relevant:

```bash
git diff --cached --name-only      # staged
git status --short                 # untracked
```

Map each changed Java class to its test class (see §Naming Conventions). For each, check changed methods (`git diff {base}...HEAD -- <file>`) and whether they already have coverage.

### Step 4 — Audit existing tests and build a coverage map

For **every** target test class (existing or to-be-created), before writing the plan:

1. **Locate** existing test file via Grep (`pattern: {ClassName}Test`, `path: src/test`, `glob: *.java`).
2. **Use the full content already read in Step 0/1** (do not re-read). If a test file surfaced here that Step 0 missed, read it now — once.
3. **Extract** every `@Test`/`@ParameterizedTest` method name; classify by scenario:

   | Existing test method | Scenario | Type |
   |---|---|---|
   | `createResource_validRequest_success` | Happy path — valid input | Integration |
   | `createResource_memberNotFound_failed` | Member not found → 418 | Integration |

4. **Mark each planned scenario:**
   - `COVERED` — existing test exercises this → **do not generate**
   - `PARTIAL` — endpoint covered but not this error code/edge → **add a method**
   - `MISSING` — no existing test → **generate**

Generate only `PARTIAL` and `MISSING`. **Never generate a method that duplicates a `COVERED` scenario**, even under a different name.

Create a new test class only if:
- No existing test class for the target
- Existing class is very large and new scenarios are a clearly separate concern
- User explicitly asks

### Step 5 — Output a numbered plan

For each file **created** or **modified**, show three sections:

```
File: src/test/.../FooControllerIntegrationTest.java  [MODIFY — adding 2 methods]

  Already covered (skip):
    ✓ createResource_validRequest_success        — happy path
    ✓ createResource_memberNotFound_failed       — member not found → 418

  Will generate:
    + createResource_duplicateOrder_failed       — duplicate order → 418   [Integration/@Negative]
    + createResource_invalidAmount_failed        — amount ≤ 0 → 400        [Integration/@Negative]
```

If all scenarios covered, state: "All scenarios for `FooController` are covered — no new tests needed."

**Wait for explicit approval** (e.g. "looks good", "go ahead") before writing code. Then read `references/test-patterns.md` and implement.

### Step 6 — Verification command

After implementing, show the exact command (do not run):

```bash
# Single test class
mvn clean test -pl <module> -am -Dtest=YourTestClassName

# Full suite
mvn clean test -pl <module> -am
```

---

## Naming Conventions

| Source class | Test class name | Test type |
|---|---|---|
| `FooController` (in `rest-web` module) | `FooControllerIntegrationTest` | Integration |
| `FooController` (unit, mock service) | `FooControllerTest` | Unit |
| `FooServiceImpl` | `FooServiceImplTest` | Unit |
| `FooRepositoryImpl` | `FooRepositoryImplTest` | Unit |
| `FooOutboundServiceImpl` | `FooOutboundServiceImplTest` | Unit |

**Name from uncovered lines:**
- Uncovered line in `*Controller` → `*ControllerTest` (unit) or `*ControllerIntegrationTest` (integration)
- In `*ServiceImpl` → `*ServiceImplTest`
- In `*RepositoryImpl` → `*RepositoryImplTest`
- In any `*OutboundServiceImpl` → `*OutboundServiceImplTest`

---

## Test Strategy: Integration vs Unit

### Integration test (`*ControllerIntegrationTest`)
Use for:
- Happy path through full stack (controller → service → DB)
- Kafka event publishing verification
- WireMock-stubbed outbound HTTP calls
- End-to-end DB state verification after the request

### Unit test (`*ControllerTest`, `*ServiceImplTest`)
Use for:
- Negative/error flows (invalid input, entity-not-found, exception propagation)
- Logic hard to trigger via HTTP (private helpers, complex branching, retry logic)
- Anything not requiring full Spring context

**Split strategy (option B):**
- Integration covers: 1 happy path per endpoint
- Unit covers: all error codes, validation failures, exceptions, edge cases

Do NOT duplicate scenarios between integration and unit tests.

### Worked example — A vs B for the same controller

`FooController` has one `POST /foo`. Reachable branches:
- happy path (service returns entity)
- `LoyaltyRuntimeException(FOO_NOT_FOUND)` → 418
- `LoyaltyRuntimeException(FOO_DUPLICATE)` → 418
- generic `RuntimeException` → 500
- body fails `@Valid` → 400

**Strategy A — Full integration** (one file, `FooControllerIntegrationTest.java`):

| # | Scenario | Tag |
|---|----------|-----|
| 1 | `createFoo_validRequest_success` | @Positive |
| 2 | `createFoo_notFound_returns418` | @Negative |
| 3 | `createFoo_duplicate_returns418` | @Negative |
| 4 | `createFoo_unexpectedException_returns500` | @Negative |
| 5 | `createFoo_invalidBody_returns400` | @Negative |

No unit test file.

**Strategy B — Split** (two files):

`FooControllerIntegrationTest.java`:

| # | Scenario | Tag |
|---|----------|-----|
| 1 | `createFoo_validRequest_success` | @Positive |
| 2 | `createFoo_notFound_returns418` | @Negative *(mandatory entity-not-found)* |

`FooControllerTest.java` (unit, MockMvc standalone):

| # | Scenario |
|---|----------|
| 1 | `createFoo_duplicate_returns418` |
| 2 | `createFoo_unexpectedException_returns500` |
| 3 | `createFoo_invalidBody_returns400` |

`createFoo_notFound_returns418` lives in **only** the integration test — never both. Same for happy path.

---

## What to Cover

### Mandatory for every endpoint (integration)
- **Happy path** (`@Positive`) — valid input, all dependencies present, correct response + DB state
- **Entity not found** (`@Negative`) — missing prerequisite returns correct error code, no DB side effects

### Mandatory for every error code (unit, if split strategy)
- One test method per `ErrorCode` returnable
- One test for unexpected `RuntimeException` → 500

### Add when applicable
- **Validation error** — missing/invalid required field → `400`
- **Duplicate / idempotency** — same request twice → conflict or idempotent
- **Kafka event** — assert event fields, topic, filter predicate inside happy path
- **Concurrent scenario** — if race conditions documented in `CLAUDE.md`

### Assertion minimum
Every test method needs ≥1 meaningful assertion. Full table in `references/test-patterns.md` (Assertion Minimum). A `verify(...)` call alone is **not** an assertion.

### Do NOT duplicate
- **Never generate a method for a scenario already covered** — run Step 4's coverage map first.
- Do not write the same scenario in both integration and unit tests.
- Do not add a new test file if the existing class can be extended.
- If asked to "generate tests for FooController" and all scenarios covered, say so instead of generating redundant tests.

---

## Common Pitfalls

- **Duplicate tests** — read the existing test class in full (Step 4) and build the coverage map before writing code. A scenario is duplicate if same endpoint + same trigger + same outcome exists under any method name.
- **Hardcoded Kafka topic strings** — use the topic properties bean. Fork suffix will be missing and tests fail in full-suite runs.
- **Shared IDs across methods** — if an ID appears in an async Kafka event, each method needs a unique ID.
- **Weak await predicates** — `Objects::nonNull` picks up intermediate records. Use a predicate checking the final expected state.
- **`isEqualToIgnoringGivenFields` missing volatile fields** — always exclude `id`, `createdDate`, `updatedDate`, `createdBy`, `updatedBy`.
- **Seeding transactional data in `@BeforeEach`** — seed master/reference data in `@BeforeEach`; seed per-test transactional data inside each method.
- **Not asserting DB side effects** — always assert saved/updated entity state; HTTP response alone is insufficient.
- **Missing `verify(service).method(args)` in controller unit tests** — proves the service was called with correct args, not just a 200.
- **Missing `verifyNoMoreInteractions` in unit tests** — without it, unexpected service calls go undetected.
- **New class when existing one could be extended** — check the existing test class first.
- **Test with no assertion** — a test that only calls `verify(...)` or only performs the request without asserting always passes. Assert ≥1 outcome (response code, body field, DB state, Kafka event field).
