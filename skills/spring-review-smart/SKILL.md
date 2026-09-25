---
name: spring-review-smart
description: Smart orchestrator — classifies changed files, selects relevant spring-review-* sub-skills, and produces a consolidated report. Auto mode (first review) or Lite mode (re-review, mandatory skills + prior findings re-check).
---

# Spring Review — Smart Orchestrator

## Purpose

Read diff, classify files, select sub-skills, invoke in parallel, aggregate findings, apply 12-domain Principal Engineer synthesis. All domain logic in sub-skills and `~/.claude/references/domains.md`. No re-implement.

---

## Multi-Agent Architecture

3-tier model. Eliminates context accumulation. Preserves accuracy.

**Tier Definitions:**

| Tier | Capability | Claude | Gemini | Cursor / other |
|------|-----------|--------|--------|----------------|
| `fast` | Mechanical/binary checks. No reasoning. | Haiku | Flash | cheap/fast tier (haiku, gpt-4o-mini, gemini-flash) |
| `capable` | Analytical: flow tracing, judgment, multi-hop reasoning. | Sonnet | Pro | capable tier (sonnet, gpt-4o, gemini-pro) |
| `reasoning` | Deep semantic reasoning: formula correctness, invariant proofs. | Opus | Pro/Ultra | strongest reasoning model available |

Resolve tier → model via platform column. Spawn/escalation instructions name tiers — hardcoded model IDs apply to Claude Code only.

**Tier 1 — Orchestrator (capable-tier, this skill)**
Classifies files, selects sub-skills, spawns sub-agents in parallel, runs correlation pass, applies 12-domain synthesis, writes report.

**Tier 2 — Sub-skill agents (parallel)**
Tier per Step 2 trigger table Tier column (Lite: Lite Step 3 table). Each agent starts fresh with only `.review-context.md`. No accumulated context.

**Tier 3 — Reasoning-tier consultant (on-demand from Tier 2 capable agents)**
Capable agents call reasoning-tier **once** on genuine P0/P1 ambiguity. Gets code snippet + narrow question. Returns `VERDICT | REASON | FIX`.

**Platform fallback — no Agent tool / sub-agent support (Gemini CLI, Cursor):** run each selected skill inline in current session, sequentially. Announce `[skill-name] running inline on: {model}`. Reasoning-tier skills and consults: strongest model available. Same checklists, same findings contract, same report — accuracy preserved; context cost higher.

---

## Announce Model

Print before output:
```
[spring-review-smart] running on: {model} | Phase: orchestrator (capable-tier)
```

---

## Pre-Step — Clarify Review Scope

Scan request for scope signal:
- Branch name(s): e.g., `feature/foo`, `main`, `master`
- Commit hash (7–40 hex chars)
- PR number: `#123`, `PR 123`, `pull/123`
- Local signal: "local changes", "uncommitted", "staged", "working tree", "not yet committed"

Formatter signal: scan for "skip format", "no format", "without formatter", "--no-formatter"
→ `{formatter_skipped}` = true. Default: false — code-formatter runs unless skipped.

API-docs signal: scan for "api docs", "api documentation", "doc staleness", "--api-docs"
→ `{apidocs_requested}` = true. Default: false — skipped unless opted in.

**Scope found** → display:
> "Reviewing: {scope description}. Proceed? (yes / change it)"

**Scope not found** → ask:
> "What should I review?
> - Branch vs branch — name both (e.g., `feature/foo` vs `master`)
> - Specific commit — provide hash
> - PR number
> - Local changes (uncommitted + staged)"

Wait. Don't proceed until scope confirmed.

### Scope Rules

| Scope | What to include |
|-------|----------------|
| Branch vs branch | Diff between named branches only |
| Specific commit | That commit's changes only |
| PR | All commits in PR vs base branch |
| Local | Uncommitted + staged in working tree |

Never include uncommitted/local changes unless explicitly requested.

### Validate Context Cache Scope

Scope confirmed: check `.review-context.md` `**Branch**` + commit hash match scope.

Mismatch → stop:
> "Context cache was built for `{cache-scope}` but you requested `{user-scope}`. Rebuild context cache targeting `{user-scope}` first."

---

## Step 0 — Verify Context Cache

Read `.review-context.md` from root.

1. Confirm first line = `<!-- review-context: {hash} -->`. Absent/stale → stop: "Context cache missing or stale — re-run your review request."
2. All steps use only content loaded here — no git commands, no independent reads. One exception: caller-count grep for `downstream-impact` trigger when method absent from Section 6.

---

## Step 0.5 — Detect Review Mode

### Priority order (highest wins)

1. **Explicit user override**:
   - `lite only`, `lite mode`, `--lite` → force **Lite mode**, skip to [Lite Mode Flow](#lite-mode-flow).
   - `auto`, `auto mode`, `full review`, `--auto` → force **Auto mode**, skip to [Auto Mode Flow](#auto-mode-flow).

2. **Existing review file** — extract branch from `**Branch**` in `.review-context.md`. Sanitize: replace `/`, `#`, `(`, `)`, space, unsafe chars with `-`. Construct: `docs/code-review/CODE-REVIEW-{branch}.md`
   - **File exists** → read fully. Confirm `action_items` has at least one entry at any priority (P0, P1, or P2).
     - Yes → **Lite mode**. Even all-P2 or resolved findings qualify — re-check verifies current status.
     - Empty table or no `action_items` section → **Auto mode**.
   - **File does not exist** → **Auto mode**.

Print after decision:
```
[spring-review-smart] Mode: AUTO | Branch: {branch} | Reason: no prior review found
[spring-review-smart] Mode: LITE | Branch: {branch} | Reason: prior review found at {path}
```

---

## Lite Mode Flow

Runs when prior review exists for branch.

### Lite Step 1 — Load Previous Findings

Read existing `docs/code-review/CODE-REVIEW-{branch}.md`.

Extract every action item from `action_items` table:
```
| Found by   | Priority                 | Item          | File        |
| security-1 | P0 — Must fix before merge | <description> | <file:line> |
```

Produce `previous_findings[]` with fields `{found_by, pri, item, file}`.

Record:
- `previous_skills_run` — `skills_run` from prior review header
- `previous_commit` — `commit` hash from prior review header
- `previous_changeset` — file list from prior review changeset section

### Lite Step 2 — Detect Uncovered New Changes

Compare current changeset (.review-context.md Section 2) against `previous_changeset`.

Identify files new in diff, absent from previous review ("uncovered changes"). Union with files listed in prior report `### Warning — Uncovered Changes Detected` section — carried entries stay uncovered until Auto run covers them.

Uncovered changes → do NOT run Auto mode. Append warning after Lite Step 5. Do NOT ask user yet.

### Lite Step 3 — Run Mandatory Skills as Parallel Agents

Spawn simultaneously:

| Skill | Tier | Condition |
|-------|------|-----------|
| `spring-review-build-runtime` | capable | always |
| `spring-review-security` | capable | always |
| `spring-review-code-formatter` | fast | always — skip only when `{formatter_skipped}` = true |

Use prompt template from Auto Step 3. Pass `model:` per Tier column. Collect all before Lite Step 4.

#### Error Handling

Same rules as Auto Step 3 Error Handling — track state, no retry, continue with successes, mandatory-fail escalation (`code-formatter` fails → P2 re-run item only), all-fail stop.

### Lite Step 4 — Re-Check Previous Findings

Per entry in `previous_findings[]`, cross-reference:
1. Current per-file diffs in `.review-context.md` Section 4.
2. Current file content — read changed file from disk when diff alone not conclusive.
3. Mandatory skill findings from Lite Step 3.

Classify each:

| Status | Meaning |
|--------|---------|
| `FIXED` | Issue gone or mandatory skills no longer flag it |
| `STILL OPEN` | Issue persists in current code |
| `CANNOT VERIFY` | Relevant file deleted or renamed |

### Lite Step 5 — Spawn be-code-reviewer

Spawn capable-tier sub-agent via Agent tool (Claude: `model: sonnet`); no sub-agent support → run inline. Pass re-check results + mandatory skill findings.

Prompt:
```
Invoke the be-code-reviewer agent. Running as sub-agent of spring-review-smart.
Mode: synthesis
Read .review-context.md from project root — already on disk.
Apply 12-domain rubric as Senior Principal Engineer. Synthesize findings below.
Reference findings by ID + title + one-line why-it-matters — do NOT re-paste full
problem/fix text. Your own new findings: IDs PE-1, PE-2, ... with full What/Why/Fix.
Return complete Principal Engineer section: Verdict + 🔴/🟠/🟡/✅ + Overall Risk + Top 3. Do NOT write files.

--- Previous Findings Re-Check ---
{paste STILL OPEN and CANNOT VERIFY entries from Lite Step 4}

--- Mandatory Skill Findings ---
{paste build-runtime, security findings from Lite Step 3}
{unless formatter_skipped: paste code-formatter findings from Lite Step 3}
```

### Lite Step 6 — Write Re-Review Report

Produce Markdown report. **Overwrite** existing `docs/code-review/CODE-REVIEW-{branch}.md`.

```markdown
## Spring Code Review — Re-Review

> **Subject**: <PR title or commit subject>
> **Reviewed**: <today's date>
> **Commit**: `<current hash>`
> **Previous commit**: `<prior review hash>`
> **Files changed**: <N>
> **Mode**: LITE
> **Mandatory skills run**: spring-review-build-runtime, spring-review-security{, spring-review-code-formatter (unless skipped)}

### Change Set (Current)

| File | Status | Categories |
|------|--------|------------|
| src/.../FooController.java | M | CONTROLLER |

### Previous Findings Re-Check

| Priority | Item | File | Status |
|----------|------|------|--------|
| P0 | <original description> | <file:line> | FIXED |
| P1 | <original description> | <file:line> | STILL OPEN |
| P2 | <original description> | <file:line> | CANNOT VERIFY |

### Principal Engineer Synthesis

{Paste complete be-code-reviewer output — Verdict, Summary, 🔴/🟠/🟡/✅, Overall Risk, Top 3.}

### Findings Detail

{Full finding blocks — new mandatory-skill findings + principal-engineer findings. Group by
priority: P0, P1, P2. Label each with readable name `{skill-name}-{n}` (Step 3.8), not raw ID.}

### Checks Summary

{One line per mandatory skill — paste each `checks:` summary line.}

### Action Items (Open Only)

| Found by | Priority | Item | File |
|----------|----------|------|------|
| build-runtime-1 | P0 — Must fix before merge | <still-open or new mandatory finding> | <file:line> |
| security-1 | P1 — Should fix before merge | <still-open or new mandatory finding> | <file:line> |
```

Apply Step 3.7 conservation check to mandatory-skill findings before writing: every ID either in synthesis or carried forward into Action Items.

Tell user file path.

**Uncovered changes detected (Lite Step 2)**: append to report AND display to user:

```markdown
### Warning — Uncovered Changes Detected

| File | Status |
|------|--------|
| src/.../NewService.java | A |

> Files changed since last Auto review not covered by any sub-skill.
> Includes entries carried forward from prior re-reviews — cleared only by Auto run.
> Run `/review` with `--auto` to trigger full Auto mode covering these files.
```

Then ask user:
> "New files not covered by previous Auto review. Run Auto mode now? (yes / no)"
> - yes → proceed to [Auto Mode Flow](#auto-mode-flow).
> - no → stop.

---

## Auto Mode Flow

Runs on first review or `--auto`.

### Step 1 — Classify Changed Files

Use cache Section 3 (File Classification) as-is — be-review-context B3 already tagged every changed file by category. Section 3 missing or empty → stop: "Cache stale or incomplete — rebuild context." Category definitions (CONTROLLER, SERVICE, REPOSITORY, ENTITY_DTO, KAFKA, REDIS, CONFIG, MIGRATION, BUILD, API_DOCS, TEST) are canonical in be-review-context Step B3; Step 2 triggers reference them.

### Step 2 — Select Skills

Select **build-runtime**, **security**, **code-formatter** always. Drop **code-formatter** only when `{formatter_skipped}` = true.

Evaluate triggers against Section 3 categories **and** Section 4 diffs — diff-level signals (state-mutating ops, new external HTTP calls, new log statements, new queries, mutable instance fields, logic changes) from Section 4 scan.

| Skill | Trigger | Tier |
|-------|---------|------|
| `spring-review-build-runtime` | **Always** | capable |
| `spring-review-security` | **Always** | capable |
| `spring-review-code-formatter` | **Always** — skip only when `{formatter_skipped}` = true ("skip format", "--no-formatter") | fast |
| `spring-review-idempotency` | CONTROLLER, SERVICE, or KAFKA with state-mutating ops | capable |
| `spring-review-integration-tests` | CONTROLLER, SERVICE, REPOSITORY, or KAFKA changed | capable |
| `spring-review-downstream-impact` | SERVICE changed AND method has multiple callers (grep to verify) | capable |
| `spring-review-api-docs` | `{apidocs_requested}` = true AND (CONTROLLER or ENTITY_DTO with contract-visible changes) — opt-in via "api docs", "api documentation", `--api-docs` | fast |
| `spring-review-kafka-middleware` | KAFKA or REDIS changed, OR new external HTTP calls added, OR CONFIG with kafka/redis/http-client properties changed | capable |
| `spring-review-breaking-changes` | ENTITY_DTO validation changed, MIGRATION added, enum values changed, CONTROLLER, SERVICE, or `@RestControllerAdvice` changed | capable |
| `spring-review-query-performance` | REPOSITORY changed, OR new queries added | capable |
| `spring-review-pom-safety` | BUILD changed, OR CONFIG with renamed/removed/changed config properties | capable |
| `spring-review-thread-safety` | SERVICE or component with `@Transactional`, `@Async`, `@Cacheable`, or mutable instance fields | capable |
| `spring-review-observability` | New entry points, new log statements, or new external dependencies | capable |
| `spring-review-migration-safety` | MIGRATION changed | fast |
| `spring-review-business-logic` | SERVICE method logic changed (conditions, formulas, state transitions) | reasoning |

**Narrow skills** (`pom-safety`, `migration-safety`, `api-docs`): spawn with injected diff slice, not full cache — see Step 3. All others are broad (read full cache).

### Step 3 — Spawn Sub-skill Agents in Parallel

Spawn all skills as parallel sub-agents via Agent tool (not Skill tool). Pass `model:` per Tier Definitions platform column — Claude: fast → `haiku`, capable → `sonnet`, reasoning → `opus`. No sub-agent support → Platform fallback (inline, sequential).

**Broad skills** (default) — read full cache:
```
Invoke the {skill-name} skill. Running as sub-agent of spring-review-smart.
The .review-context.md is already on disk at the project root — read it directly.
Apply the skill fully.
Do NOT write any files. Return findings in compact ID format per your Return Format
section — no OK tables, no empty sections. End with your checks summary line.
```

**Narrow skills** (`pom-safety`, `migration-safety`, `api-docs`) — inject diff slice, skip cache read. Need only their category's diffs. Extract matching `### {file}` blocks from Section 4 (in context from Step 0):
```
Invoke the {skill-name} skill. Running as sub-agent of spring-review-smart.
Diff slice below — do NOT read .review-context.md; apply skill to this slice only.
Base commit: {hash}. Branch: {branch}.

--- Relevant Diffs (Section 4 subset) ---
{paste ### {file} blocks for this skill's category:
  pom-safety        → BUILD files (pom.xml, build.gradle) + CONFIG property files (application*.yml/properties, bootstrap*.yml)
  migration-safety  → MIGRATION files + *Entity.java / *Document.java
  api-docs          → CONTROLLER files + *Request / *Response / *Dto}

Do NOT write any files. Return findings in compact ID format per your Return Format
section — no OK tables, no empty sections. End with your checks summary line.
```
No changed files in category → don't spawn (Step 2 triggers gate this).

Spawn all in single message — one Agent per skill, all parallel. Each sub-agent first line: `[skill-name] running on: {model} ({tier}-tier)` — capture for Skills Run table. Collect all before Step 3.6.

#### Error Handling

Per sub-agent: track state `success` | `failed` | `timeout`. Agent tool blocks until return — no wall-clock cutoff to enforce; `timeout` = tool-reported timeout.

Sub-agent fails when:
- Tool error (model error, permission denial, tool exception, tool-reported timeout)
- Empty/unrecognizable response (no findings section, no priorities)

No retry. No block. No abort. Continue with successful responses. Record name + reason in `failed_skills[]`.

Mandatory skill fails (`build-runtime`, `security`):
- Overall Risk ≥ MEDIUM
- Add P1: "Re-run {skill} manually — automated review missing this layer."

`code-formatter` fails: add P2 re-run item. No risk elevation — formatter failure is cosmetic, not merge risk.

All sub-agents fail: stop, tell user "All sub-agents failed — investigate context cache or model availability before re-running."

---

### Step 3.6 — Spawn be-code-reviewer

Spawn capable-tier sub-agent via Agent tool (Claude: `model: sonnet`); no sub-agent support → run inline. Pass all sub-skill findings. Correlation scan runs inside the agent (its correlation table) — no separate orchestrator pass.

Prompt:
```
Invoke the be-code-reviewer agent. Running as sub-agent of spring-review-smart.
Mode: synthesis
Read .review-context.md from project root — already on disk.
Apply 12-domain rubric as Senior Principal Engineer.

Rules — non-negotiable:
1. Every finding ID below must appear in output at its severity tier or higher. Reference by
   ID + title + one-line why-it-matters. Do NOT re-paste full problem/fix text — full detail
   lives in the report's Findings Detail section.
2. Scan all findings for compound patterns per your correlation table; elevate each compound
   finding one severity level (P1→P0, P2→P1).
3. Scan diff in .review-context.md for Domain 4 (Memory/GC) — no sub-skill covers this.
   Your own new findings (Domain 4, compound correlations): use IDs PE-1, PE-2, ... with full
   What/Why/Fix — they exist nowhere else.

Return complete Principal Engineer section: Verdict + 🔴/🟠/🟡/✅ + Overall Risk + Top 3. Do NOT write files.

--- Sub-skill Findings ---
{paste all collected sub-skill findings from Step 3}
```

---

### Step 3.7 — Findings Conservation Check

After be-code-reviewer returns:

1. Collect all finding IDs from Step 3 sub-skill outputs (e.g. `SEC-1`, `IDEM-3`) + correlation findings.
2. Verify each ID appears in synthesis output.
3. Missing ID → append finding verbatim to Action Items with note `[not addressed by synthesis — carried forward]`. Never drop.
4. Print: `[spring-review-smart] conservation: {n} findings in, {m} in synthesis, {k} carried forward`

---

### Step 3.8 — Expand IDs to Readable Labels (report-facing)

Compact IDs (`SEC-1`, `BR-2`) are transport only — they let sub-agents stay terse and let Step 3.7 verify conservation. **In the written report, replace every compact ID with a readable label `{skill-name}-{n}`** so any reader knows which review found it without decoding a prefix. Keep the number — it stays a unique handle for the Action Items table.

| Prefix | Report label | Prefix | Report label |
|--------|--------------|--------|--------------|
| BR | `build-runtime-{n}` | TS | `thread-safety-{n}` |
| SEC | `security-{n}` | OBS | `observability-{n}` |
| IDEM | `idempotency-{n}` | MIG | `migration-safety-{n}` |
| IT | `integration-tests-{n}` | POM | `pom-safety-{n}` |
| BL | `business-logic-{n}` | FMT | `code-formatter-{n}` |
| BC | `breaking-changes-{n}` | AD | `api-docs-{n}` |
| DI | `downstream-impact-{n}` | QP | `query-performance-{n}` |
| KM | `kafka-middleware-{n}` | PE | `principal-engineer-{n}` |

Apply the expansion everywhere in the report — Synthesis, Findings Detail, Action Items. Conservation (Step 3.7) runs on compact IDs before expansion; the map is 1:1 so no finding is lost in translation.

---

### Step 4 — Consolidated Report

```markdown
## Spring Code Review — <PR title or commit subject>

> **Reviewed**: <date>
> **Commit**: `<hash>`
> **Mode**: AUTO
> **Files changed**: <N>

**Skills run:**

| Skill | Model | Tier | Status |
|-------|-------|------|--------|
| spring-review-build-runtime | {model} | capable | ok |

**Skills skipped:**

| Skill | Reason |
|-------|--------|
| spring-review-pom-safety | no BUILD files changed |

**Skills failed:** (omit table if none)

| Skill | Reason |
|-------|--------|
| spring-review-thread-safety | sub-agent timeout |

### Change Set

| File | Status | Categories |
|------|--------|------------|
| src/.../FooController.java | M | CONTROLLER |

### Principal Engineer Synthesis

{Paste complete be-code-reviewer output — Verdict, Summary, 🔴/🟠/🟡/✅, Overall Risk, Top 3.}

### Findings Detail

{Paste full finding blocks — every sub-skill finding + every principal-engineer finding from
synthesis. Group by priority: P0 first, then P1, then P2. Carries complete problem/fix detail.
Label each block with its readable name `{skill-name}-{n}` (Step 3.8) — not the compact ID.}

#### P0
{full finding blocks}

#### P1
{full finding blocks}

#### P2
{full finding blocks}

### Checks Summary

{One line per skill — paste each sub-skill `checks:` summary line.}

### Action Items

| Found by | Priority | Item | File |
|----------|----------|------|------|
| security-1 | P0 — Must fix before merge | <one-line description> | <file:line> |
| idempotency-2 | P1 — Should fix before merge | <one-line description> | <file:line> |
| principal-engineer-1 | P2 — Follow-up | <one-line description> | <file:line> |
```

### Step 5 — Write Report to File

Write to `docs/code-review/` — mandatory. One file only.

- Branch from `**Branch**` in `.review-context.md` — no `git rev-parse`.
- File: `docs/code-review/CODE-REVIEW-{branch}.md`.
- Overwrite if exists. Create `docs/code-review/` if missing.
- Write via Write tool. Tell user path.
- `.gitignore`: read first. Append `docs/code-review/` only if absent. `docs/api/` committed only.

---

## Constraints

- **Read before commenting**: Read actual files. No inferring from class names.
- **Integration tests only**: `@SpringBootTest` or `@WebFluxTest`. No unit tests.
- **Coverage threshold**: Minimum 93%.
- **Reactive awareness**: Flag `block()` in reactive chains. `@Transactional` on reactive MongoDB — P0.
- **Redis TTL is not eviction**: Absent explicit cache eviction = P0.
- **Domain 4 (Memory)**: no sub-skill — apply `~/.claude/references/domains.md` rubric against diff.
- **Downstream impact**: Check Section 6 (Caller Analysis) of `.review-context.md`; grep as fallback.
- **Never auto-trigger Auto from Lite**: Uncovered changes → warn and ask. No auto-switch.
- **Single output file**: Auto and Lite overwrite `docs/code-review/CODE-REVIEW-{branch}.md`. No per-subskill files.
- **Compact IDs are transport-only**: `SEC-1`/`BR-2` flow sub-skill → orchestrator → synthesis. Report expands them to readable `{skill-name}-{n}` labels (Step 3.8) — never print raw prefixes to the user. Findings Detail carries full problem/fix blocks.
- **No finding lost**: Step 3.7 conservation check mandatory (on compact IDs, before expansion). Every sub-skill finding lands in synthesis or Action Items.
