---
name: spring-review-thread-safety
description: Reviews thread safety and transaction correctness. Checks singleton mutable state, AOP self-invocation trap (@Transactional/@Cacheable/@Async/@PreAuthorize bypassed by same-class calls), and transaction correctness (missing @Transactional, long transactions, wrong isolation, reactive mismatch).
---

# Spring Review — Thread Safety & Transaction Correctness

## Model Guidance

Capable-tier. First output line: `[spring-review-thread-safety] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- A reactive method carries both `@Transactional` and `@Cacheable` annotations with a `Mono<T>` or `Flux<T>` return type — the interaction between `ReactiveMongoTransactionManager` and the cache proxy is non-obvious and the bug may be silent
- AOP proxy configuration is complex (multiple layered proxies, programmatic proxy creation, `@EnableAspectJAutoProxy(proxyTargetClass = true)`) and whether a self-invocation trap applies is genuinely ambiguous

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

---

## Phase 12 — Thread Safety & Transaction Correctness

### 12.1 Shared Mutable State in Singleton Beans

**Every `@Service`, `@Component`, `@Repository`, and `@Controller` is a singleton.** Instance fields shared across all concurrent requests.

| Risk | What to detect |
|------|---------------|
| **Non-final, non-thread-safe instance field** | `private List<X> cache = new ArrayList<>()` in `@Service` — concurrent writes corrupt list. Use `ConcurrentHashMap`, `CopyOnWriteArrayList`, or move to thread-local/request-scoped bean. |
| **`SimpleDateFormat` as instance field** | Not thread-safe. Use `DateTimeFormatter` (thread-safe) or create per-call. |
| **Mutable static fields** | `private static int counter = 0` mutated without synchronization. Use `AtomicInteger`. |
| **Stateful field updated in request flow** | Any instance field written during request handling and read during another request creates a race. |

```
THREAD SAFETY RISK: Mutable singleton state
  Location: <file:line>
  Field: <fieldName> (<type>)
  Risk: Concurrent requests share this instance; writes from one request corrupt state for another.
  Fix: <use thread-safe type / move to local variable / use request-scoped bean>
```

### 12.2 AOP Self-Invocation Trap (Critical)

**Spring AOP only intercepts calls through the proxy.** When method in class `A` calls another method in **same** class `A`, call bypasses proxy — any `@Transactional`, `@Cacheable`, `@CacheEvict`, `@Async`, or `@PreAuthorize` on called method has **no effect**.

```java
@Service
public class OrderServiceImpl implements OrderService {
    public void processOrder(Order order) {
        this.saveOrder(order);  // WRONG: self-invocation — @Transactional on saveOrder is ignored
    }
    @Transactional
    public void saveOrder(Order order) { ... }
}
```

Per changed method annotated with `@Transactional`, `@Cacheable`, `@CacheEvict`, `@Async`, or `@PreAuthorize`:
1. Search for callers within **same class**.
2. If same-class caller exists and relies on annotation taking effect, flag it.

```
AOP SELF-INVOCATION RISK: @<Annotation> has no effect
  Annotated method: <ClassName#annotatedMethod> at <file:line>
  Called from same class by: <ClassName#callerMethod> at <file:line>
  Risk: @<Annotation> bypassed — transaction/cache/async/security does not apply.
  Fix: Extract <annotatedMethod> into separate Spring-managed bean and inject it,
       or use ApplicationContext.getBean(ThisClass.class).annotatedMethod() (less preferred).
```

### 12.3 Transaction Correctness

| Check | What to verify |
|-------|---------------|
| **Missing `@Transactional` on multi-step DB** | Two or more DB writes without `@Transactional` — failure between writes leaves data in partial state. |
| **Long transaction spanning HTTP calls** | `@Transactional` wrapping Feign/RestTemplate/WebClient call holds DB connection open for duration of HTTP call. Move external call outside transaction. |
| **Long transaction spanning Kafka publish** | Publishing to Kafka inside `@Transactional` block (non-transactional Kafka) means message sent even if DB rolls back — ghost event. Use outbox pattern. |
| **Missing `@Transactional(readOnly = true)`** | Service methods only reading data should use `readOnly = true`. |
| **Wrong isolation level** | For read-then-write operations (balance checks, stock deduction), verify `@Transactional(isolation = Isolation.REPEATABLE_READ)` or use optimistic/pessimistic locking. |
| **`@Transactional` on reactive Mongo** | Standard `@Transactional` does not work with reactive MongoDB — use `ReactiveMongoTransactionManager` or `inTransaction()`. Flag any `@Transactional` on method returning `Mono<T>` or `Flux<T>` with non-reactive transaction manager. |

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
TS-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `singleton_state, aop_self_invocation, transactions`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `TS: no findings.` + checks summary.

---

## Constraints

- **All Spring beans are singletons**: Mutable instance fields in `@Service`/`@Component`/`@Repository`/`@Controller` are a race condition.
- **AOP self-invocation is a silent bug**: Annotation appears correct but does nothing — most commonly missed Spring pitfall.
- **Read before commenting**: Always read full class to check for same-class callers of annotated methods.
- **Reactive + @Transactional mismatch**: Standard `@Transactional` on reactive method returning `Mono`/`Flux` is always P0 when using reactive MongoDB.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
