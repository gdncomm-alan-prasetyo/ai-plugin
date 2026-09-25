---
name: spring-review-build-runtime
description: Reviews build-time and runtime error risks. Checks compilation failures (removed methods, missing beans, type mismatches, annotation misuse), runtime exceptions (NPE, ClassCastException, LazyInit), resource leaks, and @Scheduled/@Async silent failure patterns.
---

# Spring Review — Build & Runtime Error Analysis

## Model Guidance

Capable-tier. First output line: `[spring-review-build-runtime] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- A reactive operator chain (`flatMap`, `map`, `switchIfEmpty`, `then`, `zip`) makes it genuinely ambiguous whether a `block()` call is inside or outside the reactive pipeline — position is the deciding factor between P0 and OK
- A circular dependency chain is suspected across 3+ classes and you cannot resolve the dependency graph from the files available in context

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

Focus on Java source files in `src/main`. Group by layer.

---

## Phase 3 — Build & Runtime Error Analysis

### 3.1 Build Errors

| Check | Examples |
|-------|---------|
| **Removed/renamed methods used elsewhere** | Method signature changed in service; callers still reference old signature. |
| **Missing Spring bean** | New `@Autowired`/constructor-injected dependency with no `@Bean`/`@Component`. |
| **Incompatible return types** | Service returns `Mono<X>` but caller expects `X`; `Optional<X>` unwrapped without `.get()` guard. |
| **DTO field type mismatch** | JSON field mapped to `Long` but payload sends `String`; `@JsonProperty` name mismatch. |
| **Annotation misuse** | `@Transactional` on `private` method; `@Cacheable` on non-Spring-managed class. |
| **Reactive contract broken** | Cold publisher subscribed twice; blocking call inside reactive chain (`block()` in WebFlux). |

### 3.2 Runtime Errors

| Risk | How to detect |
|------|--------------|
| **NullPointerException** | Field accessed without null check after `findById()`, `Optional.get()` without `isPresent()`, `map().get()` chain on nullable. |
| **ClassCastException** | Raw-type cast from generic collection; `Object` cast without `instanceof`. |
| **ConcurrentModificationException** | Modifying collection while iterating (especially in multi-threaded context). |
| **StackOverflowError** | Circular `@Bean` dependency or recursive method without base case. |
| **Reactive NPE** | `Mono.just(null)` — use `Mono.justOrEmpty()`; `flatMap` returning `null` instead of `Mono.empty()`. |
| **LazyInitializationException** | JPA entity lazy collection accessed outside transaction boundary. |
| **NumberFormatException / DateTimeParseException** | String-to-primitive conversion without try/catch or validation. |
| **IndexOutOfBoundsException** | `list.get(0)` without empty check; `substring` with unchecked length. |

### 3.3 Resource Leaks

| Risk | How to detect |
|------|--------------|
| **Unclosed streams/connections** | `InputStream`, `OutputStream`, `Connection`, `PreparedStatement`, `ResultSet` opened but not in `try-with-resources` or explicitly closed in `finally`. |
| **Unclosed reactive subscriptions** | `Flux`/`Mono` subscribed with `.subscribe()` but returned `Disposable` never stored — no way to cancel on shutdown. |
| **`Flux.collectList()` on unbounded source** | Collects entire unbounded stream into `List<T>` in memory, causing OOM. Use `.buffer(n)` or paginated queries. |
| **HTTP client connection not released** | `WebClient` response body not fully consumed or cancelled — keeps connection slot leased indefinitely. Always call `.bodyToMono(...)` or `.release()`. |

### 3.4 `@Scheduled` and `@Async` Silent Failure

| Risk | How to detect |
|------|--------------|
| **`@Scheduled` exception stops next run** | Uncaught exception from `@Scheduled` method cancels next execution until restart. All `@Scheduled` methods must have top-level try/catch that logs error and allows method to return normally. |
| **`@Async` swallows exceptions** | `@Async` method returning `void` swallows all unhandled exceptions unless `AsyncUncaughtExceptionHandler` configured. Verify `AsyncConfigurerSupport#getAsyncUncaughtExceptionHandler` is set, or change return type to `Future<T>`/`CompletableFuture<T>`. |
| **`@Async` on reactive method** | `@Async` on method returning `Mono<T>`/`Flux<T>` has no effect — use `subscribeOn(Schedulers.boundedElastic())` instead. |

Per risk found:

```
RUNTIME RISK: <Error type>
  Location: <file:line>
  Scenario: <when this can happen>
  Fix: <suggested safe pattern>
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
BR-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `build_errors, runtime_errors, resource_leaks, scheduled_async`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `BR: no findings.` + checks summary.

---

## Constraints

- **Read before commenting**: Always read actual file before making a finding. Do not infer from class names.
- **Reactive awareness**: `block()` inside reactive chain is P0. `Mono.just(null)` causes silent NPE downstream.
- **Annotation misuse is a build error**: `@Transactional` on `private` methods, `@Cacheable` on non-Spring beans — silently does nothing.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
