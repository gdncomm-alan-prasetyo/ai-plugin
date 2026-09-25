---
name: repo-orientation
description: Produces a quick "how this codebase works" summary for a Spring Boot repo — stack, entry points, data/messaging dependencies (including per-datastore detail like Mongo collection names and indexes, or JPA table names and indexes), how to run and test locally, and any obviously risky spots. Use when opening an unfamiliar repo, picking up a service that hasn't been touched in a while, onboarding to a new service, or asking where specific data lives (e.g. "where's this stored in Mongo", "what indexes exist on this collection"). Not a code review — read-only orientation, no findings/severity.
---

# Repo Orientation

## Model Guidance

Fast-tier. First output line: `[repo-orientation] running on: {model} (fast-tier)`

This is a summarization task, not a review — cheapest capable model is fine.

---

## Core Rule

Read-only. Never edit files, never run builds/tests without asking. The goal is a 30-second mental model of the repo, not an audit.

---

## Step 0 — Check for CodeGraph

If a `codegraph_*` MCP toolset is connected, check `codegraph_status` first (or just try `codegraph_context` — a clean "not initialized" response means skip this path). When available, it replaces the manual scanning in Step 2 and speeds up Step 3:

- `codegraph_context` with a query like `"controllers services repositories configuration"` → one call, returns the relevant symbols grouped by file — use this as Step 2's primary source instead of Glob/Grep.
- `codegraph_files` on `src/main/java` → quick package/module layout if `codegraph_context` doesn't already make it obvious.

No CodeGraph connected, or `.codegraph/` not initialized → fall back to manual `Glob`/`Grep` in Step 2 as written. Don't ask the user to run `codegraph init` just for an orientation pass — that's a heavier ask than this skill warrants; only mention it's available as an aside if genuinely relevant.

---

## Step 1 — Identify the Service

Read root `pom.xml` (or the parent pom if multi-module). Extract:
- `<artifactId>` → service name
- `<packaging>` → jar/war/pom (multi-module if `pom`)
- Parent (`spring-boot-starter-parent` version → Spring Boot version; Java version from `<properties>` or `maven.compiler.release`)
- Module list if multi-module

---

## Step 1.5 — Purpose / Responsibility

One or two sentences: what this service is *for*, in business terms — not "a Spring Boot app with 5 controllers," but "the authoritative RBAC and user-directory service, managing users/roles/permissions across three IdPs." This is the first thing someone new should read — what the service does, before what stack it runs on. Source, in order:

1. **`~/.claude/references/system-<name>.md`**, if `system-catalog` already has an entry for this repo (resolve the name via `component-map.md`) — use its opening description line verbatim. Most trustworthy source; kept current by `system-catalog`.
2. **The repo's own README.md**, if it opens with an actual description (first paragraph — skip past badges/build-status walls). Quote or lightly compress it.
3. **Neither exists** → infer one sentence from what Steps 1–3 already surfaced (dominant entity/domain names, controller base paths, external systems integrated). Mark it plainly: `(inferred — no README or system-catalog entry found)`. Never state inferred business intent as fact.

---

## Step 2 — Map the Layers

Scan `src/main/java` package structure. Identify, per module if multi-module:
- Controllers (`@RestController`/`@Controller`) — class name + base `@RequestMapping` path + endpoint count (detail in Step 2.5)
- Services (`@Service`) — just the count and names, not full logic
- Repositories (`@Repository`, Spring Data interfaces) — what they're backed by (JPA/Mongo/etc, inferred from `extends`)
- Any `@Configuration` classes worth flagging by name only (e.g. `SecurityConfig`, `KafkaConfig`)

Don't read every file — `codegraph_search`/`codegraph_context` if available is faster than manual grep for this step. Fall back to `Glob`/`Grep` for annotation patterns if not.

---

## Step 2.5 — Endpoint Detail (per controller found in Step 2)

One level more specific than "UserController exists" — every method + path someone would actually need when picking up this service, with what it does and where. Grep-based (method name, mapping annotation, adjacent Javadoc if present) — not a body read of every handler.

Per controller, per endpoint:
```
UserController (/api/user) — UserController.java
  POST /create          create a new user                        :42
  POST /update           update user fields                       :58
  POST /update-status     activate/deactivate a user                :74
  GET  /search             search users by criteria                  :105
```

Description source, cheapest first: existing Javadoc/`@Operation(summary=...)` on the method → verbatim or lightly compressed; none present → derive from the method name (`updateStatus` → "activate/deactivate a user") — plain reading of the name, not a guess about internal logic. Cite the line the mapping annotation sits on.

**This detail is Return Format only — it does not go into the `CLAUDE.md` block.** A service with many controllers can easily run 30+ endpoints; embedding all of them in a block that auto-loads every session is exactly the kind of always-on bloat worth avoiding. The `CLAUDE.md` block keeps the Step 2 summary line (controller + base path + endpoint count) only. Anyone who needs the full per-endpoint list re-runs `/orient` — cheap, grep-based, regenerated on demand rather than carried in every session's context.

---

## Step 3 — External Dependencies

Read `application.yml`/`application.properties` (and profile variants if present). Identify:
- Datastore(s) — DB URL scheme, Redis, Mongo, etc.
- Messaging — Kafka topics/consumer groups, RabbitMQ queues
- Config/secret source — Vault, Consul, config-server references
- Any other external service URLs (feign clients, `RestTemplate`/`WebClient` base URLs)

---

## Step 3.5 — Data Model Detail (per datastore found in Step 3)

One level more specific than "uses MongoDB" — this is the part that actually saves someone from grepping entity classes by hand later. Grep-based, not full reads; skip entirely if no datastore was found in Step 3.

**MongoDB** — Grep `@Document` across `src/main/java` (`glob: *.java`, `pattern: @Document`, `-A 1` to catch the class name on the next line). Per entity found:
- Collection name (`@Document(collection = "...")`, or the class name lowercased if the annotation has no explicit name)
- Indexes: grep `@Indexed`, `@CompoundIndex`, `@CompoundIndexes` in the same file — field name(s), `unique = true` if present, TTL (`expireAfterSeconds`) if present

**JPA / relational** — Grep `@Entity`/`@Table` the same way. Per entity:
- Table name (`@Table(name = "...")`, or class name if absent)
- Indexes/constraints from `@Table(indexes = ...)` or `@Table(uniqueConstraints = ...)`

**Redis** — Grep `@Cacheable`/`@CacheEvict`/`RedisTemplate` key patterns and `cacheNames`. Note TTL if configured in `application.yml` (`spring.cache.redis.time-to-live` or a custom `RedisCacheConfiguration` bean) — a cache with no visible TTL is worth a one-line note, not a full audit.

List format, one line per collection/table — this can run longer than other sections since it's the actual payoff, but stay to `name — indexes: ...` density, not full field lists:

```
Data Model:
  users (Mongo) — idx: email (unique), createdAt
  sessions (Mongo) — idx: expiresAt (TTL 3600s)
  orders (JPA, table: orders) — idx: customer_id, (status, created_at)
```

No entities found despite a datastore being configured (e.g. it's accessed some other way — raw driver, another module) → say so plainly rather than omitting the section silently: `Data Model: no @Document/@Entity classes found in this module — datastore access pattern not identified.`

---

## Step 4 — How to Run and Test Locally

- `docker-compose.yml` present? List the services it brings up.
- Test command: check `pom.xml` for surefire/failsafe profiles (e.g. `mvn test` vs `mvn verify -Pintegration`)
- Local run command (`mvn spring-boot:run` with module flag if multi-module, or note if it needs a specific profile/env var to boot)

---

## Step 5 — Flag Anything Notable (optional, only if obvious)

Only include if genuinely obvious from Steps 1–4, not a deep-dive:
- A clearly oversized class (e.g. one service file far larger than its siblings)
- Missing test directory entirely
- Hardcoded external URLs/credentials in config (flag existence, don't print the value)

Skip this section entirely rather than stretch for something to say.

---

## Step 5.5 — Conventions & Constraints (seed)

Seed the rules `be-analyst` / `be-developer` must follow — the ones that aren't obvious from the code and cost a red build or rework when missed. **Seed only:** `/sdlc-build`'s feedback loop appends the hard-won ones later; don't guess those here.

Two cheap sources (stay read-only, bounded):
- **Gate/build config** — read what actually fails a build: Sonar props (`sonar-project.properties` / pom `sonar.*` — new-code coverage %, incl. *branch* coverage, duplication, rating gates), jacoco minimums + enforcer rules in the pom, the JDK/toolchain (`toolchains.xml`, `maven.compiler.release`), formatter/checkstyle config, and the CI pipeline stage names (Jenkinsfile) — note any stage the repo flags as flaky.
- **Patterns already followed consistently** — from the Step-2 scan, 0–3 conventions the code clearly repeats (constructor injection throughout, MapStruct name-based mapping, a shared error-handling helper). A pattern earns a line only if it's genuinely consistent — not one file's choice, and never a convention you'd *impose* that the repo doesn't practice.

Filter every candidate — a line survives only if it is **all four**: non-obvious (a dev wouldn't infer it in 30s), actionable (changes a concrete decision), costly if violated (red build / failed review / runtime error / rework), and stable (a property of the repo, not one ticket). Drop generic best practice ("write tests", "follow SOLID") and ticket-specifics. **Cap ~8 bullets, one screen** — past that, keep the highest-consequence.

Format every entry — seeded here or appended later by `/sdlc-build` — the same way, so the block reads as one system, not two dialects:
```
- <rule text> — _(source: file:line, recurred: 0)_       ← seeded here, from static gate/build config
- <rule text> — _(learned: PR-<n>, recurred: 0)_          ← appended later by /sdlc-build, from a CI-fix or review comment
```
`recurred: 0` on every entry regardless of origin — it's what lets `/sdlc-build`'s CI loop bump a counter on *any* rule, seeded or learned, when the failure it's meant to prevent happens again anyway (see `sdlc-build.md` step 3 / `sdlc-orchestration.md`). A seeded rule with no `recurred:` tag is one the feedback loop can't track.

Nothing clears the filter → omit the section rather than pad it.

---

## Step 5.6 — Seed `.claude/rules/backend-api.md` (only if absent)

The `CLAUDE.md` block (Step 5.5) is ~8 bullets. `.claude/rules/backend-api.md` is the fuller, prescriptive house rulebook `be-developer` / `be-analyst` / `be-code-reviewer` read as a hard input. Seed it once so those agents have something to follow.

**Guard — create only if missing.** Glob `.claude/rules/backend-api.md` in the repo root. **Present → do not touch it.** It is the source of truth, often hand-authored and reviewed; never overwrite, never reformat. Absent → write a seed.

**This is a seed, not the polished rulebook.** Fast-tier + a bounded orientation scan can't make the judgment calls a real convention doc needs (which assertion lib, masking policy, formatter profile). So the seed is honest about that: every rule carries `file:line` evidence, gray/inconsistent areas are **flagged for a human**, not guessed, and a banner says "review + expand me." The full treatment is a separate deeper pass.

Write the file as **prose** (it lives in the target repo, read by humans + agents — not caveman). Group like this, one section per area where Steps 1–5.5 found a real, repeated pattern:

- **ARCH** — module/layer boundaries, controller→service→repo, `@Transactional` stance
- **WEB** — controller shape, path constants, validation, mandatory params/headers, response envelope
- **ERR** — how business vs framework errors are thrown/handled, stack-trace exposure
- **DI** — injection style, config mechanism (`@ConfigurationProperties` vs `@Value`)
- **DATA** — entity base class, repository base, builder style, index declaration
- **MAP** — DTO tiers, mapper discipline
- **LOG** — logging framework, log-prefix/lifecycle convention
- **TEST** — unit vs integration split, test infra (real datastore / Testcontainers / mocks), assertion style, coverage gate
- **BUILD** — JDK/toolchain, coverage gate %, enforcer/formatter, load-bearing build quirks

Per rule: a one-line statement, the `file:line` it's drawn from, and (where cheap) a right/wrong snippet. **Only rules with real evidence** — a pattern seen once is not a rule; omit it. **No rule survives without provenance.**

Reactive repo (WebFlux detected in Steps 2–3) → add a top note that a companion `reactive-programming.md` should also be authored (never-block, `onErrorResume`, `StepVerifier`, schedulers) — flag it, don't hand-author it here.

Top banner, verbatim:

```markdown
> **Auto-seeded draft** by `repo-orientation` on {ISO date}. Grounded in what the code does today, but NOT a reviewed rulebook — every `REVIEW:` line needs a human decision, and rules should be expanded/corrected against the team's real conventions. Once a human owns this file, delete this banner; `repo-orientation` will then never overwrite it.
```

Gray/inconsistent areas → a line `REVIEW: <area> — <the options seen>, team to decide` instead of a rule (e.g. `REVIEW: assertion library — JUnit Assertions and AssertJ both in use, pick one`). Never invent the decision.

Nothing clears the evidence bar (too little code, unclear patterns) → skip the seed, say so in the return summary. Don't write an empty or padded rulebook.

---

## Step 6 — Upsert the CLAUDE.md Block

No separate cache file — write straight into `CLAUDE.md`, which auto-loads into every session for free, in a fenced, machine-owned block.

1. Glob for `CLAUDE.md` at repo root.
2. **Exists** → read it, look for the markers below. Found → replace only the content between them, byte-for-byte, leaving everything else in the file untouched. Not found → append the block once, at the end of the file, separated by a blank line.
3. **Missing entirely** → create `CLAUDE.md` containing only the block below. Don't invent surrounding sections — that's the team's to write.

```markdown
<!-- repo-orientation:start -->
<!-- generated: {ISO datetime} | head: {8-char commit hash} -->
## {service} — Orientation

Purpose: {one or two sentences — what the service is for, per Step 1.5; append `(inferred)` if source was neither system-catalog nor README}
Stack: {Spring Boot version}, {Java version}, {single-module | Maven multi-module: mod-a, mod-b, ...}
Entry points: {ControllerName (base path, N endpoints)}, ... — full per-endpoint list: re-run `/orient`
Data: {datastore(s) + how accessed}
Data Model: {collection/table — idx: ...; one line per entity, or omit if no datastore}
Messaging: {topics/queues + consumer/producer class names, or "none found"}
Run locally: {docker-compose command if applicable} + {run command}
Tests: {test command(s)}
Notable: {0-2 bullets, or omit line if nothing stands out}
Conventions & Constraints: {gate rules · build invariants · consistently-followed patterns — one line each with provenance, ≤8; grows via /sdlc-build's feedback loop; omit if none clear the filter}
{if `.claude/rules/backend-api.md` exists: add line → "Full code convention: `.claude/rules/*.md` (authoritative — be-developer/reviewer follow it)"}

_Auto-generated by `repo-orientation` — do not hand-edit, edits are overwritten on next regen._
<!-- repo-orientation:end -->
```

**Entry points stays a summary line here — the per-endpoint breakdown from Step 2.5 is Return Format only**, per that step's note. Don't let the full endpoint list creep into this block; it's exactly the always-on bloat the split was meant to avoid.

**Never touch anything outside the markers.** If a `CLAUDE.md` has no markers and isn't obviously auto-generated-only (i.e. it already has real content), still just append — never rewrite, reorder, or reformat the human-authored parts.

---

## Return Format

```
## {service} — Orientation

Purpose: {one or two sentences — see Step 1.5; append `(inferred)` if not from system-catalog or README}
Stack: {Spring Boot version}, {Java version}, {single-module | Maven multi-module: mod-a, mod-b, ...}
Entry points:

  {ControllerName} ({base path}) — {File.java}
    {METHOD} {path}    {one-line description}    :{line}
    {METHOD} {path}    {one-line description}    :{line}
  ...

Data: {datastore(s) + how accessed}
Messaging: {topics/queues + consumer/producer class names, or "none found"}
Run locally: {docker-compose command if applicable} + {run command}
Tests: {test command(s)}
Notable: {0-2 bullets, or omit section if nothing stands out}
Conventions & Constraints: {gate rules · build invariants · consistent patterns — ≤8 lines with provenance, or omit}
```

Purpose leads — someone new reads what the service does before what it runs on. The full per-endpoint breakdown (Step 2.5) belongs here, in what's shown to the user this run — it's the one section allowed to run past "one screen" for a controller-heavy service, since it's ephemeral output, not something carried into every future session's context (that's the `CLAUDE.md` block's job, and it only gets the summary line — see Step 6). This is orientation, not documentation — link to files (`path:line`) instead of pasting code.

---

## Constraints

- **Read-only** — no edits, no running builds/tests without asking first. Two scoped write exceptions only: upserting the fenced block in `CLAUDE.md` (Step 6), and seeding `.claude/rules/backend-api.md` **when it does not already exist** (Step 5.6). Both explicitly marked and scoped; never touch a `.claude/rules/` file that already exists, never touch `CLAUDE.md` outside the markers.
- **Summary, not audit** — no severity/P0-P1-P2, no findings format. If something looks wrong, one line under "Notable" is enough; don't turn it into a review.
- **Don't over-read** — this should be a handful of file reads (pom, application.yml, a directory listing) plus grep sweeps for Step 3.5, not a full codebase crawl. If codegraph is available, prefer it over manual Glob/Grep sweeps.
- **Data Model stays grep-derived** — collection/table names and index annotations only, never inferred or guessed. A field pulled from `@Indexed` is fact; a field you'd have to read the whole entity to figure out isn't worth it for this skill — note "no @Document/@Entity found" instead of reading full files to compensate.
- **Block goes stale** — if `pom.xml`/`application.yml` has changed more recently than the block's own `generated:`/`head:` marker line, treat it as stale and regenerate rather than trusting it blindly.
- **Never touch `CLAUDE.md` outside the markers** — no reordering, no reformatting, no "while I'm here" cleanup of the rest of the file. If the markers are missing, append; never guess where they should go by rewriting existing sections.
