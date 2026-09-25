---
name: spring-improve-integration-tests
description: >-
  Diagnoses and fixes slow Spring Boot @SpringBootTest integration suites.
  Root cause nine times out of ten: Spring's test ContextCache keys on the
  exact @MockBean/@MockitoBean set, so N test classes with N different mock
  combos boot N separate ApplicationContexts instead of reusing one. Fixes by
  consolidating every mock into one shared base test class, then audits and
  patches the three correctness traps that consolidation creates (dispatcher
  delegation breaks, real-bean state leaking across the now-shared context,
  deprecated-API lint gates tripping on concentrated new code). Use when
  asked to speed up integration tests, cut CI build time, or explain why
  `mvn test`/`mvn verify` boots the Spring context many times. Always plan
  and get approval before editing test files. Out of scope: Testcontainers
  startup tuning, WebFlux reactor-scheduler tuning, non-Spring frameworks.
---

# Spring — Speed Up Integration Tests via Context Cache Reuse

Built from a real fix: 13 controller test classes, 13 separate `ApplicationContext` boots, cut to 1. Every trap below hit during that fix.

## Core insight

Spring's `TestContextManager` caches an `ApplicationContext` keyed on exact `MergedContextConfiguration` — active profiles, property sources, context initializers, and **exact set of `@MockBean`/`@MockitoBean` definitions**. Two test classes, one different mock, two cache keys, two full context boots (embedded servlet container, all beans, all client/repository wiring).

Many `@SpringBootTest` classes, each declaring its own mock subset on top of a shared base — that's N context boots where 1 would do. Usually the single biggest lever for `mvn test` wall-clock time. Bigger than parallel forks, bigger than JaCoCo overhead, bigger than most other suspects.

## Agent behavior

- Plan first. Never edit test files before user approves plan (Step 5).
- Scope: test files, test config, docs describing test conventions. Touch production code only if investigation proves production bug — flag it, don't fix silently inside this skill.
- Don't run `mvn test`/`mvn verify` automatically unless user asks or JDK/toolchain confirmed available locally. Report exact command instead.
- After implementing, run `/code-review` (or equivalent) on diff before calling done — traps below are exactly what a fresh review pass catches.

---

## Planning Phase (required before any edit)

### Step 1 — Find base test class, measure fragmentation

1. Find shared `@SpringBootTest` base class (grep `@SpringBootTest` across `src/test`, or ask if none exists — see "No shared base class yet" below).
2. List its `@MockBean`/`@MockitoBean` fields.
3. List every subclass. For each, grep `@MockBean|@MockitoBean`, record type + field name.
4. Count distinct mock-set combinations. N distinct combos = N context boots (assuming no other cache-fragmenting config — check next).
5. Grep whole test tree for `@DirtiesContext`, `@ActiveProfiles`, `@TestPropertySource`, `@SpyBean` — any of these also fragments cache even with identical mocks. Note every hit.
6. Check `pom.xml`/`build.gradle` for Surefire/Failsafe `forkCount`, `reuseForks`, parallel config. Note current state — don't assume unset means slow, don't assume set means fine.
7. Check for second full test run in CI (native-image agent pass, integration profile, etc.) that doubles cost independent of context caching. Note if found — usually bigger conversation than this skill covers; report it, don't fix here unless asked.

**No shared base class yet:** if `@SpringBootTest` classes don't already share a base, creating one is bigger architectural change than this skill's normal scope (new file, every test class re-parented). Still plan it, but call out larger blast radius explicitly in Step 5, get explicit sign-off, not just implicit approval.

### Step 2 — Trace every dispatcher pattern (before writing plan, not after)

This is the trap that silently breaks tests. Skip it, plan looks done, fails in CI.

Dispatcher = any bean whose job is *generic dispatch to another bean* — command executor, strategy resolver, saga orchestrator, anything shaped like `dispatcher.run(SomeHandler.class, request)` that internally does `applicationContext.getBean(handlerClass).handle(request)`.

For every controller/service touched by consolidation:

1. Grep production code for calls into any dispatcher-shaped bean (`*Executor.execute(`, `*Dispatcher.dispatch(`, `*Resolver.resolve(`, or codebase's own naming).
2. For each call site, check matching test: does it stub dispatcher directly (`when(dispatcher.execute(eq(X.class), any())).thenReturn(...)`), or stub individual handler bean (`when(individualHandler.execute(...)).thenReturn(...)`) and rely on **real** dispatcher to look up and delegate to that mocked handler?
3. Any test in second category is a landmine. Once dispatcher itself becomes shared `@MockBean`/`@MockitoBean`, it stops doing real delegation — calls through it return `null`/default unless something stubs it. That test class silently breaks.

Build a list: `{test class, dispatcher type, handler type, handler field name}` for every landmine found. This list becomes mandatory work in Step 4 — every landmine needs explicit delegating stub, not a shrug.

### Step 3 — Audit real (non-mock) shared-state mutation

Grep every test class (not just ones with most mocks) for `@Autowired` fields that are **not** `@MockBean`/`@MockitoBean` — real beans — check whether any test method calls a setter on one (`.set...(`, `.enable...(`, config mutation of any kind). `@ConfigurationProperties` beans mutated mid-test to force a scenario are the classic case.

Today, each test class gets own context, mutating real bean is contained — whole context (and mutated bean) thrown away when class finishes. After consolidation, that bean is a **singleton shared across every test class for rest of suite run**. Value left mutated by last test in class A leaks into class B, C, D — order-dependent, may not fail every run, makes it worse, not better.

For every such class found, note: which properties get mutated, test-fixture value, and bean's **true application-config default** (check `@ConfigurationProperties` class field default AND test `application.properties`/`.yml` — they can disagree; use whichever app would actually boot with).

### Step 4 — Check for deprecated mock-annotation concentration

Target Spring Boot 3.4+ (Spring Framework 6.2+)? `@MockBean` (`org.springframework.boot.test.mock.mockito.MockBean`) is deprecated for removal, replaced by `@MockitoBean` (`org.springframework.test.context.bean.override.mockito.MockitoBean`). Check which one codebase currently uses.

`@MockBean` in play, static-analysis "new code" quality gate in play (SonarQube PR analysis common case) — moving N scattered pre-existing `@MockBean` declarations into one new/heavily-changed file turns them into N **new** deprecated-API issues counted against gate, even though nothing about deprecation status changed. Plan to declare every consolidated mock as `@MockitoBean` from the start rather than discover this after failed gate. `@MockitoBean` has equivalent bean-override and reset-after-test-by-default semantics — substitution doesn't change test behavior or context-cache win.

### Step 5 — Write plan, get approval

Present numbered plan:

1. Consolidated superset of mocks (type + chosen canonical field name) going into base class, using `@MockitoBean` (or codebase's already-current equivalent).
2. Every subclass to strip, and — critically — every **field-name collision** found (same type, different name across classes, e.g. `executor` vs `commandExecutor`) with chosen canonical name and every call site needing rename. Warn explicitly: never blind find-and-replace a rename like `executor` → `commandExecutor` across a whole file — import lines often contain old name as lowercase package segment (`com.foo.command.executor.CommandExecutor`), naive replace corrupts import path. Rename call-site by call-site.
3. Every dispatcher landmine from Step 2, with exact delegating stub to add per class:
   ```java
   when(dispatcher.execute(eq(SomeHandler.class), any()))
       .thenAnswer(invocation -> individualHandlerMock.execute(invocation.getArgument(1)));
   ```
4. Every real-bean mutation from Step 3, with shared `@BeforeEach`/`@AfterEach` reset helper — `@BeforeEach` sets test-fixture value, `@AfterEach` restores **true config default** (not test-fixture value) so nothing leaks to next class regardless of run order. One helper method, called from both, so two can't drift apart.
5. Any Surefire/Failsafe tuning, called out separate from context-cache fix, with tradeoff stated (e.g. `parallel=classes` against shared context risks races on shared mocks — usually not worth it once #1 already collapsed most of the cost).
6. Anything explicitly out of scope (second CI test pass, no-shared-base-class restructure) with one-line reason it's a separate conversation.

**Wait for explicit approval.** Don't implement on "looks reasonable" — wait for "go ahead"/"approved" or equivalent.

---

## Implementation Phase

1. Add every mock from superset to base class as `@MockitoBean` (or codebase's current standard — see Step 4). Keep visibility `protected` so subclasses inherit access under existing field names.
2. Strip each subclass's local mock declarations and now-unused imports. Verify import removal doesn't break — grep type name across *whole* file (not just declaration site) before deleting import; type used only in a field declaration safe to drop, type also used in a cast or local variable elsewhere is not.
3. Apply every field-name rename from plan, call-site by call-site (see import-corruption warning in Step 5.2 above).
4. Add every dispatcher delegating stub from Step 2/3.
5. Add shared reset helper for every real-bean mutation from Step 3, called from both `@BeforeEach` and `@AfterEach`.
6. Update any docs describing old per-class-mock convention (architecture docs, testing READMEs) so next contributor doesn't reintroduce fragmentation this fix removes.

## Verification

Report exact command, don't run unless asked:

```bash
mvn clean test -pl <test module> -am
```

Ask user to confirm: test count unchanged, all green, and — if comparable — wall-clock time down. Then recommend `/code-review` (or org's review skill) on diff before merge; dispatcher-delegation and real-bean-leak traps above are exactly what a second pass catches if Step 2/3 missed something.

Static-analysis quality gate part of CI? Mention Step 4's deprecated-annotation check explicitly in PR description so gate failure (if it still happens) is fast to diagnose instead of a mystery.

---

## Common Pitfalls

- **"Tests pass locally, fail in CI" after consolidation** — usually Step 2's dispatcher trap. Locally one test class ran in isolation (fresh context, real dispatcher-ish behavior masked by coincidence), CI runs whole suite where shared mock's default (null) return actually gets exercised.
- **Flaky test that only fails when run after specific other class** — Step 3's real-bean leak. Don't chase as "flaky test," chase as missing `@AfterEach` reset.
- **Sonar/lint gate newly failing after consolidation PR touching zero production code** — Step 4. Check whether gate's failing metric is deprecated-API or code-smell count on new/heavily-touched test file, not an actual regression.
- **Renamed field compiles in file you edited, breaks a different file** — a field name collision (Step 5.2) missed in a class not checked. Grep OLD name across entire module, not just files already in plan, before calling rename complete.
- **Consolidating mocks doesn't collapse context count** — some subclass still has a `@TestPropertySource`/`@ActiveProfiles`/`@DirtiesContext` from Step 1.5 fragmenting cache independent of mocks. Find and address separately; not fixed by moving mocks around.

## Constraints

- Never implement before plan presented and approved.
- Never blind-replace a renamed identifier across a whole file — rename call-site by call-site, watch for identifier appearing inside unrelated import path.
- Never restore a mutated real-bean property to a hardcoded "looks right" value in `@AfterEach` — verify actual application-config default first (class field default AND test properties file; use whichever app would really boot with).
- Never skip dispatcher-delegation trace (Step 2) to save time — trap most likely to produce a green plan and a red CI run.
- Never fix an unrelated pre-existing bug found during audit inside this skill's diff — report it, let user decide scope.
