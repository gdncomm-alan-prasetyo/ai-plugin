---
name: be-review-context
description: Builds the BE review context cache for Spring Boot/Java projects. Collects git metadata, classifies changed files by layer, captures per-file diffs and test metadata, runs caller grep for service/repository methods, and writes .review-context.md. Delegates to spring-review-smart (code review) or generate-tests (test generation). Invoked by the review-context rule — do not call directly.
phase: context
models:
  claude: haiku
  gemini: gemini-2.5-flash
  cursor: fast
---

## Model Guidance

Context phase — lightweight model, saves tokens. Claude Code: `haiku` (spawned as subagent by `review-context` rule). Gemini CLI: `gemini-2.5-flash`. Cursor: fast model. Action phase (spring-review-smart or generate-tests) runs on Sonnet; escalates to Opus on complexity.

# BE Review Context Builder

## Announce Model

Print first:
```
[be-review-context] Model: Haiku | Phase: context (reading files, building cache)
```

## Step B0 — Extract Scope

Extract `{branch}` and `{base}` from invoking prompt.

Pattern: `"Build context for branch {branch} vs {base}"`

**Not given explicitly → resolve before running any diff, in this order. Never guess-and-proceed straight into a diff — a wrong base here means every later step (B2's diff, B4's per-file grep) runs against the wrong, possibly much larger, changeset. That's not just a wrong report, it's real token cost spent reading files that have nothing to do with this review.**

```bash
git rev-parse --abbrev-ref HEAD   # → {branch}
```

1. **Current branch has an open PR** — `gh pr view --json baseRefName -q .baseRefName` (needs `gh` authed). This is the PR's *actual* base, not a guess — use it directly, no confirmation needed.
2. **No open PR, or `gh` unavailable** — this is a local/no-PR review. Do **not** default straight to `master`/`main` and run Step B2. A release-branch-based repo (the norm here — see `sdlc-orchestration.md`'s base-branch rule) can sit 100+ files ahead of `master`; diffing against the wrong long-lived branch pulls in an entire unrelated changeset, not this review's actual scope. Instead: note the candidate (`git branch --list master` present → `master`, else `main`), and **stop, ask the user to confirm it** before touching Step B2. One question now is cheap; an accidental 100-file diff is not.

Use `{branch}` and confirmed `{base}` in all diff commands below.

---

## Step B0.5 — Reuse Orientation Block (if present)

`CLAUDE.md` at repo root, `<!-- repo-orientation:start -->` block present → read it, hold stack/module/layer info as background context, skip re-deriving service name and module layout later. Missing → no-op, continue as normal (this block is optional, never a blocker).

---

## Step B1 — Freshness Check

Run as single Bash call:

```bash
git rev-parse HEAD && git rev-parse --abbrev-ref HEAD
```

Check `.review-context.md` in root. Exists → read first 10 lines (hash, branch, base). Verify all three:

1. First line matches `<!-- review-context: {current HEAD hash} -->`
2. `**Branch**` line matches current branch name
3. `**Base**` line matches `{base}`

All three match → **skip to Step B9**.
Any mismatch → Step B2.

---

## Step B2 — Git Metadata

Run as **single Bash call**. HEAD + branch already in B1 — don't re-run:

```bash
git log --oneline -5 && \
git diff --name-status {base}...{branch} && \
git diff {base}...{branch} > .review-diff.tmp
```

Output empty → `git diff HEAD > .review-diff.tmp` (detached HEAD / local changes).

---

## Step B2.5 — Sanity-Check the Change Set Size

Count the files in B2's `git diff --name-status` output. **More than ~40 is unusual for a single review scope** — before running B3/B4 (which read/grep every one of them, the expensive part), stop and show the count + the resolved `{base}` to the user: confirm this is really the intended scope, or the base was still wrong despite Step B0's resolution. This catches a bad base that slipped through (e.g. `gh pr view` returned something unexpected, or an odd branch/PR state) before the per-file steps burn tokens on all of it.

---

## Step B3 — Classify Every Changed File

Tag each file from the `git diff --name-status` output captured in B2 — no extra git call. Canonical category definitions — spring-review-smart Step 2 triggers reference these categories from cache Section 3:

| Category | Matches |
|----------|---------|
| CONTROLLER | `*Controller.java`, `*Router.java`, `*Handler.java` |
| SERVICE | `*Service.java`, `*ServiceImpl.java` |
| REPOSITORY | `*Repository.java`, `*RepositoryImpl.java`, `*CustomRepository.java` |
| ENTITY_DTO | `*Entity.java`, `*Document.java`, `*Request.java`, `*Response.java`, `*Dto.java`, `*Command.java`, `*Event.java` |
| KAFKA | `*Producer.java`, `*Consumer.java`, `*Listener.java`, `*Publisher.java` |
| REDIS | Derive from diff content: `@Cacheable`, `@CacheEvict`, `redisTemplate`, `ReactiveRedisTemplate` — no grep. Diff content enters context at B4 — finalize REDIS tags after B4 |
| CONFIG | `*Config.java`, `*Configuration.java`, files containing `SecurityFilterChain`, `*Properties.java`, `application*.yml`, `application*.properties`, `bootstrap*.yml` |
| MIGRATION | `*.sql`, `V*.sql`, `*.yaml` under `db/` or `migrations/`, `*.xml` under `changelog/`, files containing `@ChangeUnit`, `*.json` under `mongock/` |
| BUILD | `pom.xml`, `build.gradle`, `build.gradle.kts` |
| API_DOCS | `docs/api/*.md` |
| TEST | `src/test/**/*.java` |

Output:

```
| File | Status (A/M/D) | Categories |
|------|---------------|------------|
```

---

## Step B4 — Per-File Diff for Changed Production Files

Production files (`src/main/**`, non-test, non-deleted). **Never Read full files** — Read pulls whole file into context, persists across all later calls. Grep pulls only metadata lines.

One Bash call covers metadata + diff for all files:

```bash
for f in {file1} {file2} ... {fileN}; do
  echo "=== META: $f ==="
  grep -nE "^package |^(public |abstract |final )*(class|interface|enum) |^[[:space:]]*@[A-Z]|^[[:space:]]*(public|protected)[[:space:]].*\(" "$f"
  echo "=== DIFF: $f ==="
  git diff {base}...{branch} -- "$f" | awk 'NR<=200; END{if(NR>200) print "[diff truncated — read file from disk for full context]"}'
done
```

Grep captures package, class/interface/enum name, annotations, public/protected signatures. Approximate fine — sub-skills read file from disk for precision.

Record per file:
- Package + class name
- Public method signatures
- Annotations: `@RestController`, `@Service`, `@Transactional`, `@Cacheable`, `@CacheEvict`, `@Async`, `@KafkaListener`, `@Scheduled`, `@PreAuthorize`, etc.
- File-specific diff (max 200 lines)

---

## Step B5 — Test File Metadata for Changed Test Files

No test files in diff → skip this section entirely.

Extract via grep — **never Read full test files** (same reason as B4). One Bash call:

```bash
for f in {testfile1} ... {testfileN}; do
  echo "=== $f ==="
  grep -nE "@(SpringBootTest|WebFluxTest|WebMvcTest|DataMongoTest|DataJpaTest|Test)|class .* extends |[[:space:]]void [a-zA-Z][A-Za-z0-9_]*\(" "$f"
done
```

Record per file:
- Full file path (sub-skills read full content directly via Read tool)
- Test annotation (`@SpringBootTest`, `@WebFluxTest`, `@WebMvcTest`, etc.)
- Base class (e.g. `BaseIntegrationTest`)
- All `@Test` method names

---

## Step B7 — Caller Grep for Changed Service/Repository Methods

No SERVICE or REPOSITORY files in diff → skip this section entirely.

Per SERVICE or REPOSITORY file (Step B3):

1. Extract changed methods from **Section 4 diffs** — `+` lines with method signatures. Fallback: all public methods from Step B4.
2. Pass 1 — find caller files for **all changed methods in one grep** (alternation):
   ```
   grep pattern: (method1|method2|...|methodN)
   path: src/main
   glob: *.java
   output_mode: files_with_matches
   ```

3. Pass 2 — per method, call-site detail for top 2 callers (by match count):
   ```
   grep pattern: {methodName}
   path: {callerFilePath}
   glob: *.java
   output_mode: content
   context: 2
   head_limit: 10
   ```

Record: caller file paths + up to 10 lines call-site context from top 2 callers.

---

## Step B8 — Write the BE Cache File

Get timestamp. Bash first; fall back to PowerShell on Windows:

```bash
date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || powershell -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"
```

Write `.review-context.md` to root via Write tool:

```markdown
<!-- review-context: {full HEAD commit hash} -->

# Review Context Cache

> **Generated**: {local date and time}
> **HEAD**: `{full commit hash}`
> **Branch**: `{branch name}`
> **Base**: `{base branch}`
> **Reviewer**: be-review-context

---

## 1. Commit Metadata

### Recent Commits
{output of git log --oneline -5}

---

## 2. Change Set

### File Status
{output of git diff --name-status {base}...{branch}}

---

## 3. File Classification

| File | Status | Categories |
|------|--------|------------|
{one row per changed file}

---

## 4. Per-File Diff (Production Files)

{For each changed production file (src/main/**), not deleted:}

### {relative file path}

**Annotations**: {class-level annotations}
**Layer**: {CONTROLLER / SERVICE / REPOSITORY / etc.}
**Public methods**: {comma-separated method signatures}

**Diff** (max 200 lines):
{output of git diff {base}...{branch} -- {file}, truncated at 200 lines if exceeded}

---

## 5. Test File Metadata (Changed)

{Omit this section if no test files changed.}

{For each changed test file:}

### {relative file path}

**Test annotation**: {e.g. @SpringBootTest}
**Base class**: {e.g. BaseIntegrationTest}
**Test methods**: {list of @Test method names}

> Sub-skills: read full content directly via Read tool at path above.

---

## 6. Caller Analysis

{Omit this section if no SERVICE or REPOSITORY files changed.}

{For each changed SERVICE/REPOSITORY method:}

### {ClassName#methodName}

**Caller files**: {list of file paths from Pass 1 grep}
**Caller count**: {n} caller(s) found

{call-site lines from top 2 callers — up to 10 lines per caller — file:line:content}
```

After Write, clean up temp files via Bash:

```bash
rm -f .review-diff.tmp
```

---

## Step B9 — Confirm Ready and Delegate

Output:

```
[be-review-context] Cache ready — HEAD: {short 8-char hash} | Branch: {branch} | Base: {base} | Files: {n} changed | .review-context.md
```

**Claude Code subagent** (Agent tool, `model: haiku`): stop. Parent Sonnet handles delegation.

**Otherwise** (Gemini CLI, Cursor, direct) → invoke `spring-review-smart` for code review tasks.

`review-context` rule routes test generation directly. Don't delegate to `generate-tests` from here.

---

## Constraints

- Write `.review-context.md` to root (next to `pom.xml`/`build.gradle`). Never inside `src/`.
- First line must be cache marker. Sub-skills detect freshness.
- Never truncate grep results.
- Section 4 diffs capped at 200 lines per file. Sub-skills needing full diff read file from disk.
- Skip binary files and files >1 MB. Note as skipped.
- Deleted files: record `D` in table. Don't read content.
- **Never Read full production/test files** — pulls whole file into context, persists across all calls. Grep loops (B4, B5) for metadata. Read only first 10 lines in B1.
- Batch independent Bash commands — reduces context accumulation per round-trip.
- No `.review-diff-methods.tmp` — extract method names from Section 4 diffs in context.
- Complete all steps before delegating. Cache write fails → stop and report.
- **Section 4** — per-file diffs only. Sub-skills needing full file read from disk.
- **Section 5** — test metadata only. Sub-skills needing full test content read from disk.
- **Cache schema fixed**: sections 1–6 per Step B8 template. Omit Section 5 when no test files, Section 6 when no SERVICE/REPOSITORY changed. No full-diff append section.
- **Diff scope**: always `{base}...{branch}` (three-dot diff). Never `HEAD~1`.
- **Never guess a base and immediately diff against it.** An unresolved `{base}` (Step B0) or an unexpectedly large change set (Step B2.5) both stop and ask before B3/B4 run — those two steps are where the token cost actually lands, so that's where a wrong scope needs to be caught, not after.
