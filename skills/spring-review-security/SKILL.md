---
name: spring-review-security
description: Reviews security vulnerabilities and PII leaks. Checks auth/authorization bypass, IDOR, PII in logs, injection (MongoDB $where, SQL concatenation, JPQL, SpEL, log injection), and mass assignment via BeanUtils/MapStruct/Jackson.
---

# Spring Review — Security Analysis & PII Leaks

## Model Guidance

Capable-tier. First output line: `[spring-review-security] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- Suspected IDOR: ambiguous whether resource ID (`memberId`, `tenantId`, `accountId`) comes from JWT claim or request body/path — ownership check indirect or delegate-based
- Suspected injection: SpEL expression, MongoDB operator, or SQL fragment built from user input through helper methods — injection path not direct
- Suspected auth bypass: complex `SecurityFilterChain` config (multiple beans, conditional `@Profile`-gated) — genuinely unclear if new endpoint protected

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Read `.review-context.md`. First line must be `<!-- review-context: <hash> -->` — else stop: "Run review-context first."

---

## Phase 11 — Security Analysis

### 11.1 Authentication & Authorization Bypass

| Check | What to verify |
|-------|---------------|
| **Unprotected new endpoint** | Every new `@PostMapping`/`@GetMapping`/`@RequestMapping` must be in `SecurityFilterChain`, guarded by `@PreAuthorize`/`@Secured`, or listed as public route. |
| **Role check removed or weakened** | `@PreAuthorize("hasRole('ADMIN')")` changed to `hasRole('USER')` or removed → flag. |
| **Missing method-level security** | New service methods doing sensitive ops need service-layer guard too. |
| **JWT claim not validated** | `memberId`, `tenantId` from request body instead of JWT → any authenticated user can act as another. |

### 11.2 Insecure Direct Object Reference (IDOR)

Common REST auth bug. Resource fetched/mutated using client-supplied ID without ownership check.

```java
// IDOR risk: memberId comes from request body — any authenticated caller can use any memberId
public ResponseEntity<?> getStatement(@RequestBody StatementRequest request) {
    return service.getStatement(request.getMemberId());  // no ownership check
}

// Safe: memberId taken from authenticated principal
public ResponseEntity<?> getStatement(Authentication auth) {
    String memberId = extractMemberIdFromToken(auth);
    return service.getStatement(memberId);
}
```

Per endpoint/method with client-supplied resource ID, verify:
1. ID from authenticated JWT/session (preferred), OR
2. Code explicitly checks principal owns resource.

```
SECURITY RISK: IDOR
  Location: <file:line>
  Scenario: Caller supplies <fieldName> from request body/path; no ownership check against JWT claim.
  Fix: Extract <fieldName> from Authentication principal, or add ownership validation:
       if (!authenticatedUserId.equals(resource.getOwnerId())) throw new AccessDeniedException(...)
```

### 11.3 PII Leakage in Logs

Scan all changed files for log statements (`log.info`, `log.debug`, `log.warn`, `log.error`, `logger.info`, etc.) with objects or fields containing PII.

**PII fields to flag**: email, phone number, national ID/tax ID, full name, date of birth, device ID, IP address, financial account number, card number, physical address.

```
SECURITY RISK: PII IN LOG
  Location: <file:line>
  Log statement: log.info("Processing member: {}", member)  // member has .email, .phone
  Fix: Log only non-PII identifiers (memberId, orderId). Mask or exclude PII fields:
       log.info("Processing memberId: {}", member.getMemberId())
```

Also check:
- Kafka event payloads logged at DEBUG containing PII.
- Exception messages with user-supplied data (e.g. `"Member not found: " + email`).
- HTTP request/response logging middleware without field-level masking.

### 11.4 Injection via Raw Query Building

| Risk | What to detect |
|------|---------------|
| **MongoDB `$where` / string concat** | `Query query = new Query(Criteria.where("$where").is("this.field == '" + userInput + "'"))` — use `Criteria.where("field").is(userInput)`. |
| **Native SQL string concat** | `jdbcTemplate.query("SELECT * FROM orders WHERE id = '" + id + "'", ...)` — use `?` placeholders. |
| **JPQL string interpolation** | `em.createQuery("FROM Order o WHERE o.id = " + id)` — use `setParameter`. |
| **SpEL injection** | `@PreAuthorize("hasRole('" + role + "')")` where `role` from user input. |
| **Log injection** | User input to logs without sanitization → fake log lines. Use structured logging or sanitize newlines. |

### 11.5 Mass Assignment

Entity/document populated from DTO via mapper or `BeanUtils.copyProperties` — all fields copied, including ones client shouldn't control.

Check for:
- `BeanUtils.copyProperties(request, entity)` where entity has non-writable fields.
- MapStruct mappings with sensitive target fields lacking `@Mapping(target = "...", ignore = true)`.
- Jackson `@JsonAnySetter` or `ObjectMapper.updateValue(entity, request)` on entity objects.

```
SECURITY RISK: MASS ASSIGNMENT
  Location: <file:line>
  Risk: Fields <fieldNames> on <EntityClass> copied from request DTO without exclusion.
  Fix: Use explicit allowlist — map only fields client is permitted to set.
       Exclude: @Mapping(target = "status", ignore = true)
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
SEC-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Last line — checks summary over: `auth_authorization, idor, pii_in_logs, injection, mass_assignment`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `SEC: no findings.` + checks summary.

---

## Constraints

- **Read before commenting**: Read actual endpoint, security config, and log statements before finding.
- **Check all log levels**: PII in `log.debug` still risk.
- **JWT over request body**: Resource IDs from JWT/session, not request body. Deviation = potential IDOR.
- **Mass assignment affects all fields**: `BeanUtils.copyProperties` copies all unless excluded.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
