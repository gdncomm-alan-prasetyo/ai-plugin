---
name: pr-message-generator
description: >-
  Generates a comprehensive pull request message by comparing the current
  working branch against its base branch. Detects base branch automatically,
  collects all commits and diffs, classifies changed files by layer, and
  produces a GitHub-ready PR message in a single markdown code fence covering
  summary, what changed, test verification, API spec changes, and other
  relevant context.
---

# PR Message Generator

## Purpose

Generate a complete, GitHub-ready pull request message by analyzing all commits and file changes between the current branch and its base branch. Output a single markdown code fence that the developer can paste directly into the GitHub PR creation form.

---

## Step 1 — Detect Current Branch and Base Branch

Run:

```bash
git rev-parse --abbrev-ref HEAD
git log --oneline --decorate -20
```

Determine the **base branch** using this priority order:

1. Check if the branch was explicitly created from a known branch by scanning `git log --oneline --decorate` for the merge-base with common base branches: `main`, `master`, `develop`, `staging`.
2. Run:
   ```bash
   git merge-base --fork-point main HEAD 2>/dev/null || \
   git merge-base --fork-point master HEAD 2>/dev/null || \
   git merge-base --fork-point develop HEAD 2>/dev/null || \
   git merge-base --fork-point staging HEAD 2>/dev/null
   ```
3. Use the first branch that returns a valid merge-base commit.
4. If none of the above work, fall back to `origin/HEAD` or ask the user to specify.

Record: `CURRENT_BRANCH` and `BASE_BRANCH`.

---

## Step 2 — Collect Commits on This Branch

Run:

```bash
git log {BASE_BRANCH}..HEAD --oneline
git log {BASE_BRANCH}..HEAD --format="%H|%s|%b" --no-merges
```

Capture:
- Total number of commits
- Commit subjects (one-liners)
- Any commit body text (for context, e.g., ticket IDs, detailed explanations)

---

## Step 3 — Collect the Full Diff

Run:

```bash
git diff {BASE_BRANCH}...HEAD --stat
git diff {BASE_BRANCH}...HEAD --name-status
git diff -U1 {BASE_BRANCH}...HEAD
```

Capture:
- Files changed summary (`--stat`)
- File status list (`--name-status`): Added (A), Modified (M), Deleted (D), Renamed (R)
- Full unified diff

---

## Step 4 — Classify Changed Files

Tag each changed file with one or more categories:

| Category | Matches |
|----------|---------|
| CONTROLLER | `*Controller.java`, `*Router.java`, `*Handler.java` |
| SERVICE | `*Service.java`, `*ServiceImpl.java` |
| REPOSITORY | `*Repository.java`, `*RepositoryImpl.java`, `*CustomRepository.java` |
| ENTITY_DTO | `*Entity.java`, `*Document.java`, `*Request.java`, `*Response.java`, `*Dto.java`, `*Command.java`, `*Event.java` |
| KAFKA | `*Producer.java`, `*Consumer.java`, `*Listener.java`, `*Publisher.java` |
| REDIS | Files whose diff contains `@Cacheable`, `@CacheEvict`, `redisTemplate`, `ReactiveRedisTemplate` |
| CONFIG | `*Config.java`, `*Configuration.java`, `SecurityFilterChain`, `*Properties.java` |
| MIGRATION | `*.sql`, `V*.sql`, Liquibase `*.yaml`/`*.xml`, Mongock `@ChangeUnit`, MongoDB `*.json` migrations |
| BUILD | `pom.xml`, `build.gradle`, `build.gradle.kts` |
| API_DOCS | `docs/api/*.md` |
| TEST | `src/test/**/*.java` |
| INFRA | `Dockerfile`, `docker-compose*.yml`, `*.yaml` under `.github/`, `*.yml` CI/CD files |

Produce an internal table (not shown in PR message) for your own analysis in Step 5.

---

## Step 5 — Analyze Changes by Category

Based on the classified files and the full diff, extract:

### 5a. Changed Endpoints (CONTROLLER files)
For each modified controller, list:
- HTTP method + path (added, modified, or removed)
- Request body / param changes (fields added/removed/renamed)
- Response body changes (fields added/removed/renamed)
- Auth / permission changes

### 5b. Changed Business Logic (SERVICE files)
For each modified service, summarize:
- What logic was added, changed, or removed
- Any new dependencies introduced

### 5c. Schema / Data Changes (ENTITY_DTO, MIGRATION files)
- New fields added or removed from entities/DTOs
- Database migrations added (table, column, index)
- Enum value additions or removals

### 5d. Infrastructure / Config Changes (CONFIG, BUILD, INFRA)
- Dependency additions or version bumps
- Configuration property changes
- CI/CD pipeline modifications

### 5e. Test Coverage
- New test classes or methods added
- Test scenarios covered (positive / negative / edge cases)
- If no tests changed, note it explicitly

### 5f. Breaking Changes
Identify any of:
- Removed or renamed public API endpoint
- Request/response field removed or type changed
- Enum value removed
- Backward-incompatible database migration

---

## Step 6 — Read Key Files for Context

For each CONTROLLER file in the change set that is not deleted, read its full content to extract:
- Exact endpoint paths (`@GetMapping`, `@PostMapping`, etc.)
- Request/response DTO references

For each MIGRATION file, read its full content to extract the exact DDL or document operation.

This ensures the PR message contains accurate endpoint paths and schema details, not guesses from the diff alone.

---

## Step 7 — Compose the PR Message

Using all information collected in Steps 1–6, compose a PR message following the template below. Fill every section with real content — do **not** leave placeholder text. If a section has no applicable content (e.g., no API changes), write a brief "N/A — no API changes in this PR" instead of omitting the section.

### PR Message Template

```markdown
## Summary

<!-- 2–4 sentences: what this PR does and why. Link to the ticket/issue if one is mentioned in commit messages. -->

{Concise summary of what this PR accomplishes and the motivation behind it.}

---

## What Changed

<!-- Bullet list grouped by type. Use sub-bullets for detail. -->

### Features / Enhancements
- {Change 1}
- {Change 2}

### Bug Fixes
- {Fix 1}

### Refactoring / Cleanup
- {Refactor 1}

### Configuration / Infrastructure
- {Config change 1}

---

## API Spec Changes

<!-- Fill this section if any Controller, DTO, or Service interface changed. -->
<!-- If no API changes: "N/A — no API surface changes in this PR." -->

### New / Modified Endpoints

| Method | Path | Change | Notes |
|--------|------|--------|-------|
| {GET/POST/…} | `/api/v1/…` | Added / Modified / Removed | {brief note} |

### Request / Response Changes

| Endpoint | Field | Change | Type | Required |
|----------|-------|--------|------|----------|
| `POST /api/v1/…` | `fieldName` | Added / Removed / Renamed | `String` | Yes/No |

### DTO / Schema Changes

| Class | Field | Change | Notes |
|-------|-------|--------|-------|
| `FooRequest` | `barField` | Added | Must be non-null |

---

## Database / Migration Changes

<!-- Fill if any migration files changed. Otherwise: "N/A — no migrations in this PR." -->

| Migration | Type | Description |
|-----------|------|-------------|
| `V20240401__add_foo_column.sql` | ALTER TABLE | Adds nullable `bar` column to `foo_table` |

---

## Test Verification

<!-- Describe exactly how you verified this works. Be specific. -->

### Automated Tests
- [ ] {Test class name} — {what it covers}
- [ ] {Existing test updated to cover new case}

### Manual Verification
- [ ] {Step 1: describe what you ran / clicked / called}
- [ ] {Step 2: describe expected result and what you observed}

### Test Scenarios Covered
| Scenario | Type | Result |
|----------|------|--------|
| {Happy path description} | Positive | Pass |
| {Error / edge case description} | Negative | Pass |

---

## Breaking Changes

<!-- List anything that is NOT backward-compatible. -->
<!-- If none: "None — this PR is fully backward-compatible." -->

- {Breaking change 1 — describe impact and migration path}

---

## Dependencies / Configuration

<!-- New environment variables, feature flags, or config properties required. -->
<!-- If none: "None." -->

| Key | Value / Default | Required | Notes |
|-----|----------------|----------|-------|
| `NEW_ENV_VAR` | `default` | Yes | Used for {purpose} |

---

## Checklist

- [ ] Code compiles and all tests pass locally
- [ ] No secrets or credentials committed
- [ ] API documentation updated (if endpoint changed)
- [ ] Database migration is rollback-safe (expand-contract pattern followed)
- [ ] No breaking changes, OR breaking changes are documented above
- [ ] Relevant reviewers tagged
```

---

## Step 8 — Output the PR Message

Print the composed PR message inside a single fenced code block using triple backticks:

````
```markdown
{full PR message content here}
```
````

Tell the user:
> PR message generated for `{CURRENT_BRANCH}` → `{BASE_BRANCH}` ({N} commits, {M} files changed). Copy the content above into the GitHub PR description field.

---

## Constraints

- **Never guess endpoint paths** — read the controller files to get exact paths.
- **Never leave template placeholders** — replace every `{…}` with real content or an explicit N/A note.
- **One code fence only** — the entire PR message must be in a single ` ```markdown ``` ` block so the user can copy it in one action.
- **Base branch detection is mandatory** — do not assume `main` without checking. Run the merge-base commands in Step 1.
- **Commit messages are inputs, not outputs** — summarize their meaning; do not just list raw `git log` output verbatim in the PR message.
- **If the branch has no commits ahead of base**, stop and tell the user: "No commits found between `{CURRENT_BRANCH}` and `{BASE_BRANCH}`. Nothing to generate a PR message for."
- **Checklist items are fixed** — do not remove checklist items. Add items if the change set warrants it (e.g., add a Kafka schema compatibility item if Kafka consumers changed).
