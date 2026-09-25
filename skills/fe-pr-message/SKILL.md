---
name: fe-pr-message
description: >-
  Generates a comprehensive pull request message for frontend (Vue/JavaScript/TypeScript)
  projects by comparing the current branch against its base branch. Detects
  base branch automatically, collects commits and diffs, classifies changed
  files by FE layer (view, component, composable, store, router, util, style,
  test), and produces a GitHub-ready PR message covering summary, what changed,
  component/composable changes, test verification (Vitest + Playwright), and
  breaking changes.
---

# FE PR Message Generator

## Purpose

Generate a complete, GitHub-ready pull request message for a Vue/JavaScript/TypeScript frontend project by analyzing all commits and file changes between the current branch and its base branch. Output a single markdown code fence ready to paste into GitHub.

---

## Step 0 — Read Repo Docs

Read `CLAUDE.md` at repo root first. Contains repo-specific context — stack, conventions, scripts, known gotchas — often with its own doc steps or links to further docs. Follow those steps, build context fast, skip re-discovering repo from scratch.

Skip step if `CLAUDE.md` missing.

---

## Step 1 — Detect Current Branch and Base Branch

Run:

```bash
git rev-parse --abbrev-ref HEAD
git log --oneline --decorate -20
```

Determine the **base branch** using this priority order:

1. Scan `git log --oneline --decorate` for merge-base with common base branches: `main`, `master`, `develop`, `staging`.
2. Run:
   ```bash
   git merge-base --fork-point main HEAD 2>/dev/null || \
   git merge-base --fork-point master HEAD 2>/dev/null || \
   git merge-base --fork-point develop HEAD 2>/dev/null || \
   git merge-base --fork-point staging HEAD 2>/dev/null
   ```
3. Use the first branch that returns a valid merge-base commit. If none work, ask the user.

Record: `CURRENT_BRANCH` and `BASE_BRANCH`.

---

## Step 2 — Collect Commits on This Branch

Run:

```bash
git log {BASE_BRANCH}..HEAD --oneline
git log {BASE_BRANCH}..HEAD --format="%H|%s|%b" --no-merges
```

Capture commit subjects and any body text (ticket IDs, explanations).

---

## Step 3 — Collect the Diff

Run stat and file list first:

```bash
git diff {BASE_BRANCH}...HEAD --stat
git diff {BASE_BRANCH}...HEAD --name-status
```

Then read diffs for **production files only** (VIEW, COMPONENT, COMPOSABLE, STORE, SERVICE, UTIL, ROUTER, TYPES — from Step 4 classification). Skip TEST_UNIT, TEST_E2E, and CONFIG files to avoid loading large test diffs. If a PACKAGE file changed, read only the `package.json` diff (skip lock files).

```bash
git diff {BASE_BRANCH}...HEAD -- {prod_file_1} {prod_file_2} ...
```

If the total `--stat` shows fewer than 20 changed files and fewer than 500 insertions, you may run the full diff instead:

```bash
git diff {BASE_BRANCH}...HEAD
```

---

## Step 4 — Classify Changed Files (FE categories)

Tag each changed file:

| Category | Matches |
|----------|---------|
| VIEW | `src/views/**/*.vue`, `src/pages/**/*.vue` |
| COMPONENT | `src/components/**/*.vue`, `*.vue` elsewhere |
| LAYOUT | `src/layouts/**/*.vue` |
| COMPOSABLE | `src/composables/**/*.{js,ts}`, files starting with `use` |
| STORE | `src/stores/**/*.{js,ts}`, `src/store/**/*.{js,ts}` |
| ROUTER | `src/router/**/*.{js,ts}`, route definition files |
| SERVICE | `src/services/**/*.{js,ts}`, `src/api/**/*.{js,ts}` |
| UTIL | `src/utils/**/*.{js,ts}`, `src/helpers/**/*.{js,ts}` |
| TYPES | `src/types/**/*.ts`, `*.d.ts` |
| STYLE | `*.scss`, `*.css`, `src/styles/**` |
| TEST_UNIT | `**/*.spec.{js,ts}`, `**/*.test.{js,ts}` under `src/` or `tests/` |
| TEST_E2E | `tests/integrations/**/*.spec.{js,ts}`, `playwright/**` |
| CONFIG | `vite.config.*`, `vitest.config.*`, `tsconfig.*`, `jsconfig.*`, `.env*` |
| PACKAGE | `package.json`, `package-lock.json` |

Note: IAM repos often colocate component logic in `src/components/<feature>/js/*.js` (Options API, not `composables/`). Classify these as COMPONENT, not COMPOSABLE — COMPOSABLE is only files under `composables/` or a `use*` export.

If repo has `vue3/` folder (vue2-to-vue3 migration), paths above are under `vue3/src/`, not plain `src/`.

---

## Step 5 — Analyze Changes by Category

### 5a. UI Changes (VIEW, COMPONENT, LAYOUT)
- What components or views changed?
- Template structure changes (new UI elements, removed sections)
- Props/emits interface changes
- Accessibility or responsive behavior changes

### 5b. State & Logic Changes (COMPOSABLE, STORE, SERVICE)
- What composables or store modules changed?
- New state, getters, or actions
- API call changes (endpoints, payloads, error handling)

### 5c. Routing Changes (ROUTER)
- New or removed routes
- Guard or redirect changes
- Lazy-loading changes

### 5d. Style Changes (STYLE)
- New design tokens used
- Layout or spacing changes
- Responsive breakpoint changes

### 5e. Test Coverage
- New unit specs (Vitest or Jest, per repo) or integration specs (`blibli-integration` CLI / Playwright, per repo) added
- Coverage changes on touched files — check repo's own gate (Sonar quality gate or `vite.config.js` `coverage.include`/thresholds). No fixed IAM-wide percentage confirmed — report actual number from `npm run unit` output, don't assume one
- If no tests changed, note it explicitly

### 5f. Breaking Changes
- Removed or renamed component props/emits
- Store shape changes affecting consumers (Pinia or Vuex)
- Route path changes
- API endpoint or payload changes

### 5g. Dependencies (PACKAGE)
- New packages added
- Version bumps — flag `@blibli/blue.*` / `@blibli/blue-design-tokens` bumps explicitly (design system version drift)
- Any BLUE 2 → BLUE 3 package swap (`@blibli/dls` → `@blibli/blue.*`)
- Any `npm audit` concerns

---

## Step 6 — Compose the PR Message

```markdown
## Summary

{2–4 sentences: what this PR does and why. Link to ticket if mentioned in commits.}

---

## What Changed

### Features / Enhancements
- {Change 1}

### Bug Fixes
- {Fix 1}

### Refactoring / Cleanup
- {Refactor 1}

### Style / UI
- {Style change 1}

---

## Component / Composable Changes

<!-- Fill if VIEW, COMPONENT, COMPOSABLE, or STORE changed. Otherwise: "N/A" -->

| File | Change | Notes |
|------|--------|-------|
| `src/components/Foo.vue` | Modified | {brief description} |
| `src/composables/useFoo.js` | Added | {brief description} |

---

## Test Verification

### Automated Tests
- [ ] {unit spec — Vitest/Jest per repo} — {what it covers}
- [ ] {integration spec — blibli-integration/Playwright per repo} — {what flow it covers}

### Coverage
- Touched files in unit-test scope: {list files} — line coverage: {actual % from `npm run unit` output; note repo's own gate if configured}
- Integration-only surfaces: {list or "none"}

### Manual Verification
- [ ] {Step 1: route/action you verified}
- [ ] {Step 2: expected vs observed}

---

## Breaking Changes

<!-- List anything NOT backward-compatible. If none: "None." -->

- {Breaking change and migration path}

---

## Dependencies / Configuration

<!-- New env vars, packages, or config. If none: "None." -->

| Key / Package | Change | Notes |
|--------------|--------|-------|
| `package-name` | Added v1.2.3 | {purpose} |

---

## Checklist

- [ ] `npm run unit` passes
- [ ] `npm run build` succeeds
- [ ] Integration specs updated for changed UI flows (`npm run integration` / `blibli-integration` / Playwright, per repo)
- [ ] Coverage meets repo's own gate (Sonar quality gate or `vite.config.js` thresholds — no fixed IAM-wide % assumed)
- [ ] No secrets, tokens, or credentials committed or logged
- [ ] No `v-html` with unsanitized user content
- [ ] No BLUE 2 (`@blibli/dls`) and BLUE 3 (`@blibli/blue.*`) components mixed in touched files
- [ ] No breaking prop/emit changes without version note
- [ ] Relevant reviewers tagged
```

---

## Step 7 — Output the PR Message

Print the composed message inside a single fenced code block:

````
```markdown
{full PR message content here}
```
````

Tell the user:
> PR message generated for `{CURRENT_BRANCH}` → `{BASE_BRANCH}` ({N} commits, {M} files changed). Copy the content above into the GitHub PR description field.

---

## Constraints

- **Never leave template placeholders** — replace every `{…}` with real content or an explicit N/A.
- **One code fence only** — entire PR message in a single ` ```markdown ``` ` block.
- **Base branch detection is mandatory** — do not assume `main` without checking.
- **If no commits ahead of base**, stop and tell the user: "No commits found between `{CURRENT_BRANCH}` and `{BASE_BRANCH}`. Nothing to generate a PR message for."
- **Checklist items are fixed** — do not remove items. Add Playwright-specific items if E2E specs changed.
