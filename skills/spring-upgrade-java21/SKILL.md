---
name: spring-upgrade-java21
description: "Upgrades a Maven Spring Boot project to Java 21 in two passes. Pass 1 (always first) — detects service name from root pom.xml `<artifactId>`, runs probes across pom.xml (parent + modules), Spring Boot, Lombok, Byte Buddy, surefire/failsafe, Dockerfile, Jenkinsfile, GitHub Actions, and removed-API usage; writes JAVA21-UPGRADE-PLAN-{service}.md to project root; STOPS for user review. Pass 2 (only when user explicitly approves) — reads the service-scoped plan, applies edits with per-category compile gate, deletes repo-local Dockerfile (CI owns image builds), rewrites every non-`java21` token in Jenkinsfile to `java21`, then verifies. Pass 1 is delegated to the cheapest available fast model (e.g. Claude Haiku, Gemini Flash, GPT-4o-mini) for cost; Pass 2 runs in the current capable session. Out of scope: Spring Boot 2 → 3 (javax → jakarta) migration, GraalVM native-image debugging beyond Jenkinsfile config."
---

# Spring — Upgrade to Java 21

**Design principle — always plan to disk first, never edit before approval, fail loud not silent.**

This skill runs in **two passes**. The first pass is read-only and always produces a plan file the user can review. The second pass implements the plan, gated on explicit user approval.

---

## Startup — Resolve service name, then decide pass

### Step A — Resolve service name (always first)

The plan file is **scoped per service** so multiple repos / multiple Spring services in the same workspace don't collide.

Check `CLAUDE.md` at repo root for a `<!-- repo-orientation:start -->` block first — if present, it already names the service and module list. Use it to skip straight to Sanitize below. Still confirm the artifactId against root `pom.xml` if the block looks stale (Spring Boot/Java version changed) — Pass 1's plan needs it exact.

Resolution order (no block, or block stale):

1. Read root `pom.xml`. Extract `<artifactId>` directly under `<project>` (NOT inside `<parent>` or `<dependency>`). That is the service name.
2. If the root pom has `<packaging>pom</packaging>` and the artifactId looks generic (e.g. `parent`, `root`), prefer the directory basename: `basename "$(pwd)"`.
3. Fallback if no `pom.xml` exists at root: directory basename.

Sanitize: lowercase, replace any character not in `[a-z0-9-]` with `-`, collapse repeats, strip leading/trailing `-`.

Examples:
- `<artifactId>my-service-api</artifactId>` → `my-service-api`
- `<artifactId>com.foo.MyService</artifactId>` → `com-foo-myservice`
- Directory `app-my-service-api` → `app-my-service-api`

Bind this as `{service}` for the rest of the run. The plan filename is:

```
JAVA21-UPGRADE-PLAN-{service}.md
```

### Step B — Decide which pass to run

Check if `JAVA21-UPGRADE-PLAN-{service}.md` exists at the project root.

| State | Pass | Action |
|---|---|---|
| File **does not exist** | **Pass 1** | Run detection, write plan, STOP for review |
| File exists with `<!-- status: pending-approval -->` on line 1 | Ask user | "Plan exists at `JAVA21-UPGRADE-PLAN-{service}.md`. Reply `approve` to proceed with implementation, `re-scan` to regenerate the plan, or `cancel` to stop." |
| File exists with `<!-- status: approved -->` on line 1 | **Pass 2** | Read plan, implement, verify |
| File exists with `<!-- status: completed -->` on line 1 | Ask user | "Upgrade already completed for this HEAD. Re-scan?" |

**Sanity check before Pass 2:** the `<!-- service: {name} -->` line in the plan must equal the `{service}` resolved in Step A. If it differs (e.g., user copied a plan file from another repo), abort with: "Plan service name `{plan-service}` does not match current project `{service}`. Aborting to avoid cross-service contamination."

**Never skip Pass 1.** Even if the user says "just upgrade now", run detection and write the plan. The plan is the audit trail.

> Legacy: if a non-scoped `JAVA21-UPGRADE-PLAN.md` (no `-{service}` suffix) exists from a previous version of this skill, treat it as not-found and write the new scoped name. Tell the user once: "Found legacy `JAVA21-UPGRADE-PLAN.md`; using new per-service name `JAVA21-UPGRADE-PLAN-{service}.md`. You can delete the legacy file."

### Step C — Model-split routing

Pass 1 is read-only probing — cheap. Pass 2 applies edits and gates each on a Maven compile — needs judgment. Split them across models so the expensive capable model isn't burned on grep work.

Check the invocation prompt for the literal marker `subagent-pass-1`.

| Situation | Action |
|---|---|
| Pass 1 needed, marker **absent** (top-level invocation) | Spawn a subagent on the **cheapest fast model available in the current harness** (see table below). Pass the subagent prompt below. After it returns, surface the plan-ready line to the user and STOP — do not proceed to Pass 2 in the same turn, even if user asks. |
| Pass 1 needed, marker **present** (you are the subagent) | Run Pass 1 inline. Write the plan. Output the plan-ready line. STOP. |
| Pass 2 needed (`<!-- status: approved -->`) | Run inline in the current capable session. No subagent. |

Pick the model by harness — use whatever fast/cheap tier is currently available. If none of the listed models is available, fall back to the cheapest fast model the harness offers; if no model split is possible (no Agent tool, single-model harness), run Pass 1 inline in the current session and note this in the output.

| Harness | Pass 1 model (cheap/fast) | Pass 2 model (capable) |
|---|---|---|
| Claude Code | `haiku` (current Claude Haiku, e.g. `claude-haiku-4-5`) — pass via Agent tool's `model` field | current capable Claude (Sonnet / Opus) — current session |
| Gemini CLI | Gemini Flash (current — e.g. `gemini-2.5-flash` or successor) — separate session | Gemini Pro (current) — separate session |
| Cursor | any fast tier: claude-haiku, gpt-4o-mini, gemini-flash | any capable tier: claude-sonnet, gpt-4o, gemini-pro |
| Other / unknown | cheapest fast model the harness exposes | default capable model |

Subagent prompt (same regardless of harness):

> "Invoke the spring-upgrade-java21 skill with marker `subagent-pass-1`. Complete Pass 1 only (probes P1–P11, write `JAVA21-UPGRADE-PLAN-{service}.md` with `<!-- status: pending-approval -->` on line 1), output the plan-ready line, then STOP. Do not run Pass 2 and do not edit any project file other than the plan."

---

# PASS 1 — Detect and Plan (read-only)

Run all probes. Capture results. Write `JAVA21-UPGRADE-PLAN-{service}.md`. Stop.

## P1 — Maven coordinates

For parent `pom.xml` and every module `pom.xml`:

Grep `pattern: "<java.version>|maven.compiler|<source>|<target>|spring-boot-starter-parent"`, `glob: "**/pom.xml"`, `output_mode: content`.

Capture: `<java.version>`, `<maven.compiler.release>`, legacy `<source>`/`<target>`, Spring Boot parent version, module count.

## P2 — Library compatibility

Grep `pattern: "lombok|byte-buddy|mockito|maven-surefire|maven-failsafe|maven-compiler-plugin"`, `glob: "**/pom.xml"`, `output_mode: content`.

| Library | Min for Java 21 | Why |
|---|---|---|
| Lombok | 1.18.30 | Annotation processing |
| Byte Buddy | 1.14.18 | Class-file format |
| Mockito | 5.x | Inline mocking + Byte Buddy |
| maven-surefire-plugin | 3.2.5 | Reflection requires `--add-opens` |
| maven-failsafe-plugin | 3.2.5 | Same |
| maven-compiler-plugin | 3.11+ | `<release>` support |

## P3 — Surefire/failsafe argLine

Grep `pattern: "argLine|--add-opens"`, `glob: "**/pom.xml"`. Note presence of `--add-opens java.base/java.lang=ALL-UNNAMED`, `java.util`, `java.lang.reflect`.

## P4 — Toolchains plugin

Grep `pattern: "maven-toolchains-plugin"`, `glob: "**/pom.xml"`. Capture pinned JDK version. Label PRESENT@JDK{n} / ABSENT.

## P5 — Dockerfile

Use the Glob tool to locate Dockerfiles — avoids shell compatibility issues across platforms:

```
Glob pattern: Dockerfile
Glob pattern: docker/Dockerfile*
```

If found:
- Read it (Read tool) — note base image, FROM lines
- Grep `pattern: "Dockerfile"`, `path: .`, `output_mode: files_with_matches` — find references
- Cross-check `docker-compose*.yml`, `Jenkinsfile`, `Makefile`, `scripts/`, `README.md`

Classify:
- **ABSENT** — no Dockerfile
- **DEAD** — only self-referenced → safe to delete in Pass 2
- **LIVE** — referenced by deploy/CI surface → BLOCKER for auto-deletion

## P6 — Jenkinsfile java tokens

If `Jenkinsfile` exists, Read it. The Grep tool does not support negative lookaheads, so use a two-pass approach:

Pass 1 — find all java version-like tokens:
```
Grep pattern: "java\d+"
glob: "Jenkinsfile"
output_mode: content
-n: true
```

Pass 2 — filter out `java21` (already correct) from the results in your analysis. Keep only:
- Literal version tokens: `java8`, `java11`, `java17`, `java19`, `java20`
- `build_config.javaN` keys
- `reachability` / native-image config nested under `javaN` keys

Drop noise: `JAVA_HOME`, comments retained for history, unrelated identifiers.

Build a candidate list of {token, line} pairs to rewrite to `java21`.

## P7 — CI workflows

```bash
ls .github/workflows/*.yml 2>/dev/null
```

If found, Grep `pattern: "java-version"`, `glob: ".github/workflows/*.yml"`. Capture each value.

## P8 — Removed/internal API usage

Grep across `src/main` and `src/test`:

```
pattern: "sun\\.|com\\.sun\\.|SecurityManager|finalize\\(|javax\\.xml\\.bind"
glob: "*.java"
output_mode: content
```

List file:line for each hit.

## P9 — SB 2 vs 3 sanity

Grep `pattern: "javax\\.annotation|jakarta\\.annotation"`, `glob: "**/*.java"`, `output_mode: count`. If both appear → BLOCKER (mid-migration project, this skill is not for SB 3).

## P10 — Other JDK hints

Read if present:
- `.mvn/jvm.config`
- `.sdkmanrc`
- `.tool-versions`

## P11 — Local environment

```bash
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
java -version 2>&1 || true
# Unix
./mvnw -v 2>/dev/null | head -5 || mvn -v 2>/dev/null | head -5 || true
# Windows (PowerShell)
.\mvnw.cmd -v 2>$null | Select-Object -First 5
```

## Write `JAVA21-UPGRADE-PLAN-{service}.md`

Write to project root using the Write tool. Format:

```markdown
<!-- status: pending-approval -->
<!-- service: {service} -->
<!-- head: {full HEAD hash} -->
<!-- generated: {ISO datetime} -->

# Java 21 Upgrade Plan — {service}

> **Service**: `{service}`
> **Project**: {repo name or path}
> **Branch**: `{branch}`
> **HEAD**: `{8-char hash}`
> **Generated by**: spring-upgrade-java21 (Pass 1)

---

## Readiness Scorecard

| # | Probe | Finding | Status |
|---|---|---|---|
| P1 | Maven java.version | {value or absent} | {PASS / NEEDS BUMP} |
| P1 | Spring Boot parent | {version} | {PASS / NEEDS BUMP / OK-IN-SCOPE} |
| P2 | Lombok | {version} | {PASS / NEEDS BUMP to 1.18.30} |
| P2 | Byte Buddy | {version or unmanaged} | {PASS / NEEDS BUMP to 1.14.18} |
| P2 | Mockito | {version} | {PASS / NEEDS BUMP} |
| P2 | maven-surefire-plugin | {version} | {PASS / NEEDS BUMP to 3.2.5} |
| P2 | maven-failsafe-plugin | {version} | {PASS / NEEDS BUMP to 3.2.5} |
| P3 | argLine --add-opens | {present / missing} | {PASS / NEEDS ADD} |
| P4 | maven-toolchains-plugin | {present @ JDK X / absent} | {PASS / NEEDS ADD} |
| P5 | Dockerfile | {ABSENT / DEAD / LIVE} | {PASS / DELETE-CANDIDATE / BLOCKER} |
| P6 | Jenkinsfile java tokens | {n tokens} | {PASS / NEEDS REWRITE} |
| P7 | GitHub Actions java-version | {values} | {PASS / NEEDS BUMP} |
| P8 | Removed/internal API hits | {n} | {PASS / REVIEW} |
| P9 | SB 2 vs 3 imports | {CONSISTENT / MIXED} | {PASS / BLOCKER} |
| P10 | JDK hint files | {found / none} | (info) |
| P11 | Local java -version | {output} | (info) |

**Verdict**: {READY / NEEDS WORK / BLOCKED}

---

## Proposed Changes

{Numbered list. Each item: file path, action, before/after snippet, rationale. Include only items needed based on findings — skip PASS items.}

### 1. MODIFY pom.xml (parent)
- Set `<java.version>21</java.version>`
- Set `<maven.compiler.release>21</maven.compiler.release>`
- Drop `<source>`/`<target>` if redundant

**Why**: pin compile target to 21 across all modules.

### 2. MODIFY pom.xml (parent) — surefire / failsafe
- Bump `maven-surefire-plugin` to 3.2.5
- Bump `maven-failsafe-plugin` to 3.2.5
- Add argLine: `--add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED`

**Why**: Java 21 strong-encapsulates JDK internals; reflective tests fail without `--add-opens`.

### 3. MODIFY pom.xml (parent) — add maven-toolchains-plugin pinned to JDK 21
**Why**: ensures Maven uses JDK 21 even if `JAVA_HOME` points elsewhere.
**User action required**: `~/.m2/toolchains.xml` must have a `<jdk>` entry for version 21.

### 4. MODIFY pom.xml — library bumps
{Per library flagged in P2.}

### 5. MODIFY child pom.xml files
{Only if P1 found child overrides; otherwise omit.}

### 6. DELETE Dockerfile {only if P5 = DEAD}
**Why**: image building is owned by CI (Jenkins shared library produces the runtime image from `build_config.java21`). Repo-local `Dockerfile` is dead code that drifts from CI.
**Action**: `git rm Dockerfile`; remove `.dockerignore` if only used by it.

{If P5 = LIVE, replace this item with:}
> ⚠️ **BLOCKER — Dockerfile is referenced by:**
> - {file:line for each reference}
>
> Resolve manually before re-scanning. The skill will not delete a live Dockerfile.

### 7. MODIFY Jenkinsfile — rewrite java tokens
{For each token from P6:}
- Line {N}: `"javaN"` → `"java21"`
- Line {N}: `build_config.javaN: { ... }` → `build_config.java21: { ... }`

Leave untouched: `JAVA_HOME` references, comments retained for history.

### 8. MODIFY .github/workflows/*.yml {only if P7 found them}
- `java-version: '11'` / `'17'` → `'21'`

### 9. MODIFY src/**/*.java — replace removed-API usages {only if P8 found them}
{Per file:line.}

### 10. (Optional) MODIFY pom.xml — bump spring-boot-starter-parent
{Only if SB < 2.7.18. SB 3.x is NOT in scope for this skill.}

---

## How to proceed

1. **Review this plan**. Edit it if you want to remove or adjust any item.
2. When ready, change the first line to `<!-- status: approved -->`.
3. Re-invoke the skill (say "upgrade to java 21" again, or `/spring-upgrade-java21`). It will read this plan and start Pass 2.

To regenerate the plan from scratch (e.g., after committing changes), say "re-scan java 21 plan" or delete this file and re-invoke.

---

## Out of scope

- Spring Boot 2 → 3 migration (`javax` → `jakarta`)
- GraalVM native-image debugging beyond Jenkinsfile config
- Auto-fixing source code beyond clearly removed APIs
```

After writing, output exactly one greppable plan-ready line:

```
[spring-upgrade-java21] Plan ready — HEAD: {short8} | Service: {service} | Verdict: {READY / NEEDS WORK / BLOCKED} | Items: {n} | Blockers: {n} | JAVA21-UPGRADE-PLAN-{service}.md
```

Then a short follow-up line for the user:

```
Review the plan, edit if needed, then change line 1 to `<!-- status: approved -->` and re-invoke to apply.
```

**STOP. Do not proceed to Pass 2 in the same session even if the user asks — the orchestrator handles the handoff to the capable model after approval. Do not call Edit, Write, or `git rm` on any project file beyond `JAVA21-UPGRADE-PLAN-{service}.md`.**

---

# PASS 2 — Implement (only when status: approved)

## Pre-flight

1. Re-read `JAVA21-UPGRADE-PLAN-{service}.md` (Read tool).
2. Confirm line 1 is `<!-- status: approved -->`. If not, abort with: "Plan not approved. Set line 1 to `<!-- status: approved -->` and retry."
3. Compare `<!-- head: {hash} -->` in plan vs current `git rev-parse HEAD`. If they differ → ask user: "Plan was generated against {old hash}, current HEAD is {new hash}. Re-scan or proceed anyway?"
4. Run `git status`. If dirty, ask user to commit/stash first — keeps the upgrade as a clean diff.
5. Detect Maven wrapper: check if `mvnw` (Unix) or `mvnw.cmd` (Windows) exists at project root. Use the appropriate one throughout Pass 2. If neither exists, fall back to `mvn`.

   ```bash
   # Unix/Mac
   ls mvnw 2>/dev/null && echo "use ./mvnw" || echo "use mvn"
   # Windows (PowerShell)
   Test-Path mvnw.cmd
   ```

## Apply

For each numbered item in the plan, in order:

1. Apply the edit (Edit tool for modifications, `git rm` via Bash for DELETE).
2. Run the compile gate using the wrapper detected in pre-flight:

   ```bash
   # Unix
   ./mvnw clean compile -pl <touched module> -am
   # Windows
   .\mvnw.cmd clean compile -pl <touched module> -am
   ```

   For changes that touch parent pom.xml, run on the root without `-pl`.

3. **If the gate fails**: STOP. Report which item failed and the error. Do NOT proceed. Ask user how to handle (rollback that item, fix manually, skip, abort).

4. For Jenkinsfile token rewrites: prefer Edit with surrounding context per token over `replace_all` to avoid touching `JAVA_HOME` etc.

## Verify

After all items applied (use the wrapper detected in pre-flight):

```bash
# Unix
./mvnw clean install -DskipTests
./mvnw test
./mvnw verify
# Windows
.\mvnw.cmd clean install -DskipTests
.\mvnw.cmd test
.\mvnw.cmd verify
```

```bash
java -version
```

Plus follow-up sanity:
- Grep `pattern: "Dockerfile"`, `path: .` — confirm no stale references after deletion
- Re-grep Jenkinsfile for `java(?!21\\b)\\w*` — should match nothing relevant

## Mark complete

Update `JAVA21-UPGRADE-PLAN-{service}.md` line 1 to:
```
<!-- status: completed -->
```

Append at the bottom:
```markdown
---

## Completion Log

- **Completed**: {ISO datetime}
- **HEAD after upgrade**: `{new hash}`
- **Files modified**: {list}
- **Files deleted**: {list}
- **Verification results**:
  - `mvn clean install`: {PASS / FAIL}
  - `mvn test`: {PASS / FAIL}
  - `mvn verify`: {PASS / FAIL}
  - `java -version`: {output}
- **Follow-ups**: {anything user should still do manually, or "none"}
```

Output:

```
[spring-upgrade-java21] Pass 2 complete — upgrade applied and verified.
  Files modified: {n}
  Files deleted: {n}
  Build: {PASS / FAIL}
  Tests: {PASS / FAIL}

JAVA21-UPGRADE-PLAN-{service}.md updated to status: completed. Safe to commit.
```

---

## Constraints

- Use Read for files, Grep for searches, Edit/Write for modifications, `git rm` via Bash for deletions.
- Pass 1 writes ONLY `JAVA21-UPGRADE-PLAN-{service}.md` — no other project file is touched.
- Pass 2 requires `<!-- status: approved -->` on line 1 of the plan. No exceptions.
- Never edit child poms when parent change suffices.
- Never bump Spring Boot major version (2.x → 3.x) — out of scope.
- If detection finds project already on Java 21 with all plugin versions OK and no findings, write a minimal plan with verdict `READY` and zero items, and tell the user no upgrade is needed.
- Never delete a Dockerfile classified as LIVE — escalate as a blocker.