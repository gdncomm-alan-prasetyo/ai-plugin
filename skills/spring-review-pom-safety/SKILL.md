---
name: spring-review-pom-safety
description: Reviews pom.xml/build.gradle changes for Spring Boot upgrades, Java version changes, DB driver compatibility, managed dependency drift, auto-configuration changes, config property renames, security defaults, deprecated API usage, and hardcoded dependency/plugin version literals that should move to a `<properties>` placeholder.
---

# Spring Review — Dependency & pom.xml Safety

## Model Guidance

Capable-tier. First output line: `[spring-review-pom-safety] running on: {model} (capable-tier)`

### Reasoning-Tier Escalation

Max one consult per invocation. Genuine P0/P1 ambiguity only — batch ambiguous findings.

Triggers:
- A **Spring Boot major version bump** is detected (2.x → 3.x, or 3.x → 4.x) — the scope of auto-configuration removals, security default changes, managed dependency drift, and mandatory migration steps is too broad for Sonnet to assess comprehensively. Ask Opus for a focused list of breaking changes and required actions specific to the detected codebase patterns.
- A **Java major version bump** is detected (11 → 17, or 17 → 21) — removed APIs, module system restrictions (`--add-opens`), and deprecated GC flag changes need deep version-specific knowledge. Ask Opus to assess risk for patterns observed in the diff.

Escalate: spawn reasoning-tier sub-agent — Claude: Agent tool, `model: opus`; other agents: strongest reasoning model per platform. Description `Consult: [topic in 5 words]`. Prompt = relevant code (≤30 lines) + one specific question + `Respond only with: VERDICT: [P0|P1|P2|OK] / REASON: [one paragraph] / FIX: [minimal code or description]`.
OK verdict → drop finding. Label incorporated verdict `[reasoning-tier consultation]`. Call fails/times out/no stronger model available → keep own analysis, append `[reasoning-tier consultation failed — own verdict only]`.

---

## Phase 0 — Change Set

Diff slice provided in prompt → use it, skip cache. Read `pom.xml`/`build.gradle` from disk for full content as needed.

Else read `.review-context.md`. Validate: first line = `<!-- review-context: <hash> -->`. Absent/stale → stop: "Run `review-context` first."

---

## Phase 9 — Dependency & pom.xml Safety

### 9.1 Identify What Changed

Categorise each version change:
- **Spring Boot parent** (`spring-boot-starter-parent`/`spring-boot-dependencies` BOM)
- **Java compiler** (`maven.compiler.source`, `<java.version>`, toolchain config)
- **Database drivers**: MongoDB, PostgreSQL, MySQL, R2DBC variants
- **Spring framework** (if overriding Spring Boot's managed version)
- **Test libraries** (JUnit, Testcontainers, WireMock, Awaitility)
- **Other major libraries** (Jackson, Resilience4j, Kafka clients, Flyway/Liquibase/Mongock)

### 9.2 Spring Boot Version Upgrade Checks

| Check | What to verify |
|-------|---------------|
| **Managed dependency drift** | Run `mvn dependency:tree` and compare. Libraries no longer overridden may jump unexpectedly. |
| **Removed/deprecated auto-configuration** | Check `@SpringBootApplication`, `spring.factories`, `AutoConfiguration.imports` — verify they still resolve. |
| **Config property renames** | Check `application.properties`/`application.yml` for renamed or removed properties. |
| **Security defaults** | Spring Security defaults change between versions (CSRF, session management, password encoder). |
| **Actuator endpoint changes** | Verify `/actuator/health`, `/actuator/info` still correctly exposed. |
| **Deprecated API usage** | Search for APIs marked `@Deprecated` in new version. |

```
SPRING BOOT UPGRADE: <old-version> → <new-version>
  Compile risk: <API removals or auto-config changes detected>
  Runtime risk: <config property renames, security default changes>
  Deprecated APIs in code: <file:line — deprecated method/class and replacement>
  Recommended action: <migration steps>
```

### 9.3 Java Version Upgrade Checks

| Check | What to verify |
|-------|---------------|
| **Removed APIs** | APIs removed between Java versions (e.g. `sun.*` packages, `SecurityManager`, `Thread.stop()`). |
| **New language features** | Records, sealed classes, pattern matching — confirmed compatible with compiler version. |
| **Bytecode compatibility** | All dependencies support new bytecode version. |
| **Reflection access** | Java 9+ module system restricts deep reflection. Libraries using reflection may need updated versions. |
| **GC / JVM flags** | JVM startup flags in `Dockerfile` or deployment config may reference removed GC options. |

```
JAVA VERSION CHANGE: <old-version> → <new-version>
  Removed API usage: <file:line>
  Reflection / module risk: <library + reason>
  Bytecode compatibility risk: <dependency + detected class version>
  Recommended action: <upgrade dependency or add --add-opens flag>
```

### 9.4 Database Driver & Plugin Version Checks

#### MongoDB Driver

| Change | Risk |
|--------|------|
| Driver major version bump | Query builder API changes (`Criteria`, `Update`, `Aggregation` DSL). |
| Codec/serialization changes | BSON codec registry changes can silently alter how custom types are serialised. |
| Connection pool config renames | `maxConnectionIdleTime`, `connectionsPerHost` renamed in newer drivers. |
| Spring Data MongoDB version | Deprecated `MongoOperations` methods and query derivation behaviour changes. |

#### PostgreSQL / MySQL Driver

| Change | Risk |
|--------|------|
| Major bump | SSL default changes, timezone handling changes, `allowPublicKeyRetrieval` flag changes. |
| JDBC URL parameter renames | Some parameters renamed between major driver versions. |
| HikariCP version | Pool config keys may change. |

#### R2DBC

| Change | Risk |
|--------|------|
| `r2dbc-postgresql`/`r2dbc-h2` version | Codec changes, `ConnectionFactory` API updates, `io.r2dbc.spi` interface changes. |

```
DB DRIVER CHANGE: <driver> <old-version> → <new-version>
  API breaking change: <method/class affected>
  Runtime risk: <connection pool config, SSL, timezone>
  Recommended action: <updated config or code fix>
```

### 9.5 Other Library Compatibility

Per other library version change:
1. Check changelog for **breaking changes** between old and new version.
2. Search project code for usages of flagged breaking APIs.
3. Specifically check:
   - **Jackson**: `ObjectMapper` config, `@JsonDeserialize` custom classes, module registration.
   - **Resilience4j**: Config DSL and annotation changes between 1.x and 2.x.
   - **Kafka clients**: Producer/consumer config key renames; `enable.idempotence` default changes.
   - **Flyway/Liquibase/Mongock**: Migration naming conventions, checksum recalculation after version bump.
   - **Testcontainers**: Image version + API changes.

### 9.6 Hardcoded Version Literals

Check every added/changed `<dependency>`, `<parent>` override, and `<plugin>` block in `pom.xml`.

| Check | What to verify |
|-------|---------------|
| **Inline literal version** | `<version>1.2.3</version>` hardcoded directly on a `<dependency>`/`<plugin>`, instead of `<version>${some.version}</version>` referencing a `<properties>` entry. |
| **Duplicate literal across modules** | Same literal version string repeated in 2+ module `pom.xml` files (multi-module reactor) — drifts silently when one module gets bumped and others don't. |
| **Duplicate literal within one pom** | Same literal repeated for 2+ dependencies in one file (e.g. two Jackson modules pinned separately) — one misses a future bump. |
| **BOM-managed dependency** | Dependency already covered by an imported BOM (`spring-boot-dependencies`, custom BOM) needs no `<version>` at all — an inline literal here is redundant AND risks silently overriding the BOM's version. Flag regardless of whether it matches the BOM's version. |
| **Property already exists but unused** | A `${xxx.version}` property already defined in `<properties>` for this dependency, but the new/changed line hardcodes the literal instead of referencing it. |

Not a finding: a property definition itself (`<my-lib.version>1.2.3</my-lib.version>` inside `<properties>`) — that's the correct pattern, not the violation.

```
POM VERSION HYGIENE: <dependency/plugin artifactId>
  Current: <version>1.2.3</version>  (hardcoded in <file>:<line>)
  Problem: <redundant BOM override | duplicated across N modules | property exists unused | no property backing at all>
  Fix: define <artifactId>.version in <properties> (or reuse existing property `${x}`), reference via <version>${artifactId.version}</version>
```

---

## Return Format

Return findings only — no OK tables, no empty sections, no rows for passed checks.

Per finding:

```
POM-{n} | P0|P1|P2 | {file:line} | {short title}
  problem: {what + why it matters — 1–2 sentences}
  fix: {concrete fix. P0: verbatim Before/After code blocks mandatory. P1/P2: description enough}
```

Number findings sequentially. P0 = must fix before merge. P1 = should fix before merge. P2 = follow-up.
Body finding templates above define required content — fold their fields into `problem:`/`fix:` lines.

Per version change, one line: `version: {dependency} {old}→{new} | risk={LOW|MEDIUM|HIGH}`

Last line — checks summary over: `spring_boot, java_version, db_driver, other_libs, version_hygiene`.
`checks: risk=[{failed}] ok=[{passed}] na=[{not applicable}]`

No findings → return `POM: no findings.` + checks summary.

---

## Constraints

- **pom.xml scope**: Only run when `pom.xml`/`build.gradle` is in diff. Skip entirely otherwise.
- **Check all version axes**: When Spring Boot changes, check all three — Spring Boot, Java, DB driver.
- **Read actual pom.xml diff**: Do not assume what changed.

---

## Output

Sub-agent: return findings per Return Format — never write files. Standalone: write same findings to `docs/code-review/CODE-REVIEW-{branch}.md` (branch from `**Branch**` in `.review-context.md`; sanitize `/`, `#`, `(`, `)`, space → `-`); tell user path.
