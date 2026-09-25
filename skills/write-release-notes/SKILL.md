---
name: write-release-notes
description: >-
  Generates human-friendly release notes between two git tags. Parses natural
  prompts for output mode (markdown file or compact chat) and tag range; asks
  only for what's missing. Analyzes merge commits with Jira URLs. File mode:
  full deploy-focused Markdown. Chat mode: merge changelog for MS Teams / Slack.
  Use for release notes, changelog, or version summary.
---

# Write Release Notes

Run inside **target project repo** (not this skills repo).

**Primary audience:** developers preparing deploy. They must grasp logic changes + **critical deploy items** (system_parameter, config, properties) from file mode output.

---

## Step 0 — Parse & Validate Inputs

Read user prompt first. Extract what you can. **Only stop when something required is still missing** after parsing.

User can type naturally — order of words does not matter. Examples that parse fine:

- `teams release notes v2.1.0 to v2.3.0`
- `changelog from previous to current as md`
- `write release notes for slack between v1.0.0 and v2.0.0`

### 0a. Detect output mode

Scan prompt for intent. First match wins if multiple.

| Mode | Recognize (any) |
|------|-----------------|
| **file** | `markdown`, `md`, `md file`, `file`, `docs`, `confluence`, `github release`, `write to file`, `save as` |
| **chat** | `ms teams`, `teams`, `slack`, `discord`, `telegram`, `chat`, `compact`, `channel`, `paste`, `post to` |

Found → record `OUTPUT_MODE`. Not found → `OUTPUT_MODE = null`.

Do **not** default to file or chat when absent.

### 0b. Detect tag range

Scan prompt for tag pair. Flexible patterns:

| Pattern | Resolve |
|---------|---------|
| `from v1.2.0 to v2.3.0`, `v1.2.0 to v2.3.0`, `between v1.2.0 and v2.3.0` | `FROM_TAG`, `TO_TAG` |
| `v1.2.0..v2.3.0` | same |
| `previous` + `current` (any order in prompt) | `FROM_TAG` = 2nd newest, `TO_TAG` = newest (`git tag --sort=-version:refname`) |
| two version-like tokens (`v?\d+\.\d+…`) | earlier → `FROM_TAG`, later → `TO_TAG` |

While parsing, OK to run helper commands (e.g. list tags) — does not mean generation started:

```bash
git tag --sort=-version:refname | head -15
```

Found both ends → validate tags exist:

```bash
git rev-parse --verify "refs/tags/{TAG}^{commit}" 2>/dev/null
```

Record `FROM_TAG`, `TO_TAG` when resolved.

Not found → `FROM_TAG` / `TO_TAG` = null. One tag only → treat range as **missing** (not half-resolved).

### 0c. Gate — proceed or respond

| OUTPUT_MODE | Tag range | Action |
|-------------|-----------|--------|
| ✓ | ✓ | Proceed to Step 1 |
| ✓ | ✗ | Reply friendly — need tag range. Show recent tags from `git tag`. Include **accepted prompt examples** (below) |
| ✗ | ✓ | Reply friendly — need output mode (file or teams/slack). Include **accepted prompt examples** |
| ✗ | ✗ | Reply friendly — need both. Include **accepted prompt examples** |

**Tone:** helpful, not blocking. Acknowledge what you already parsed.

Example when only tag range found:

> Got tag range `v2.1.0` → `v2.3.0`. Where should output go — **markdown file** or **teams/slack**?
>
> Accepted prompts:
> - `release notes md file from v2.1.0 to v2.3.0`
> - `release notes for ms teams from v2.1.0 to v2.3.0`

Example when only output mode found:

> Got output: **ms teams**. Which tags to compare?
>
> Recent tags: `v2.3.0`, `v2.2.0`, `v2.1.0` …
>
> Accepted prompts:
> - `teams release notes from v2.1.0 to v2.3.0`
> - `slack changelog from previous to current`

### 0d. Error template (when stopping)

Use when required input still missing. Always include **copy-paste examples**.

```
I can generate release notes once two things are clear:

**Still need:** {output mode | tag range | both}
{If partial: **Already got:** {what was parsed}}

**Accepted prompts** (copy and adjust):

• release notes md file from v2.1.0 to v2.3.0
• write changelog for ms teams from v2.1.0 to v2.3.0
• slack release notes from previous to current
• markdown release notes between v1.0.0 and v2.0.0

**Tag tips:** use two tags (`from X to Y`) or `previous to current`.
**Output tips:** say `md file` / `markdown` OR `teams` / `slack` / `compact chat`.
```

`FROM_TAG` = `TO_TAG` → stop with same template + ask for two different tags.

---

## Step 1 — Resolve Project Name

Detect `PROJECT_NAME` from target repo.

### Detection priority

| Order | Source | How |
|-------|--------|-----|
| 1 | Maven | Root `pom.xml` — `<artifactId>` under `<project>` (not `<parent>` / `<dependency>`) |
| 2 | npm | Root `package.json` — `"name"` |
| 3 | Gradle | `settings.gradle*` → `rootProject.name` |
| 4 | Git remote | `git remote get-url origin` basename without `.git` |
| 5 | Directory | `basename "$(pwd)"` |

Sanitize for filenames: lowercase, `.` `_` spaces → `-`, strip invalid chars.

### Output path (file mode only)

```
docs/release-notes/{PROJECT_NAME}-RELEASE-NOTES-{TO_TAG}.md
```

User path override OK. Always prefix filename with `{PROJECT_NAME}-`.

---

## Step 2 — Resolve Jira Base URL (before merge analysis)

Run **once** before processing merges. Required for URL column.

```bash
# 1) Range commits
git log {FROM_TAG}..{TO_TAG} --format="%s%n%b" | grep -oE 'https://[a-zA-Z0-9.-]+\.atlassian\.net/browse/[A-Z][A-Z0-9]+-[0-9]+' | head -1

# 2) If empty — widen to all history
git log --all --format="%s%n%b" | grep -oE 'https://[a-zA-Z0-9.-]+\.atlassian\.net/browse/[A-Z][A-Z0-9]+-[0-9]+' | head -1
```

From match `https://host.atlassian.net/browse/IAM-123` → `JIRA_BASE_URL=https://host.atlassian.net/browse/`

Record `JIRA_BASE_URL` or `null` if no match.

### Per-merge Jira URL (mandatory algorithm)

For each merge with a Jira key — **always** populate Jira field. Never leave blank when key exists.

```bash
git log -1 --format="%s%n%b" {MERGE_SHA}
```

1. **URL in commit** — grep `https://…atlassian.net/browse/[A-Z][A-Z0-9]+-\d+` → use **verbatim**
2. **Key in subject/body** — regex `[A-Z][A-Z0-9]+-\d+` (also check branch name in subject `feature/IAM-123-foo`)
3. **Key + `JIRA_BASE_URL` set** → `JIRA_URL="${JIRA_BASE_URL}${KEY}"` — **must print this string** in output
4. **Key only, base null** → print key text only

**Verify before compose:** every merge row with a key must have non-empty Jira cell. If step 3 applies, cell = full `https://…` URL string (backticks in md file, plain in chat).

---

## Step 3 — Collect Commit History

```bash
git log {FROM_TAG}..{TO_TAG} --oneline
git log {FROM_TAG}..{TO_TAG} --format="%H|%s|%b|%an" --no-merges
git log {FROM_TAG}..{TO_TAG} --merges --format="%H|%P|%s|%b|%an"
```

Zero commits → stop: "No commits between `{FROM_TAG}` and `{TO_TAG}`."

---

## Step 4 — Analyze Merge Commits

For **each** merge:

```bash
git log -1 --format="%B" {MERGE_SHA}
git diff {MERGE_SHA}^1..{MERGE_SHA}^2 --stat
git diff {MERGE_SHA}^1..{MERGE_SHA}^2 --name-status
```

Apply Jira URL algorithm from Step 2.

### Exclude (do not list)

Branch sync, `sync/*`, trivial diff (lockfile/version only).

### Include (feature-related)

`feature/*`, `fix/*`, PR merges with production diff, config / `system_parameter` touches.

Per row: **Author**, **Branch/PR**, **Jira URL** (full string when resolvable), **Summary** (production logic, no tests).

---

## Step 5 — Collect Aggregate Diff (file mode only)

Skip heavy diff synthesis for **chat** mode — chat uses merge changelog only.

```bash
git diff {FROM_TAG}..{TO_TAG} --stat -- . \
  ':(exclude)src/test' ':(exclude)**/*.spec.*' ':(exclude)**/*.test.*' \
  ':(exclude)features/**' ':(exclude)tests/**' ':(exclude)integrations/**'
```

Scan CONFIG / SYSTEM_PARAM for **Configuration & System Parameters** section.

---

## Step 6 — Group Changes (file mode only)

Production logic only in Highlights / What's New / Bug Fixes / Improvements. Tests → Technical Appendix only.

---

## Step 7 — Compose Release Notes

Read `references/template.md`.

### File mode

Full Markdown template — all sections. Merged Work Jira column = backtick-wrapped full URL when key exists.

### Chat mode — merge changelog only

**Only** title + merge changelog. No Highlights, What's New, Bug Fixes, Improvements, Breaking, Deploy sections.

Shape:

```
**{PROJECT_NAME} — Release {VERSION_DISPLAY}**
{FROM_TAG} → {TO_TAG} · {YYYY-MM-DD}


**Changelog**
• {Author} · {branch/PR} · {full Jira URL} — {summary}
• {Author} · PR #124 — {summary}
```

**Spacing:** **two empty lines** after title block (double newline) before `**Changelog**`. One empty line after `**Changelog**` header before first bullet.

Jira: when key in merge commit → **must** print full URL on that bullet line (not omitted).

---

## Step 8 — Deliver Output

### File mode

1. Write Markdown to path.
2. Confirm path + range + merge count.
3. Preview Highlights only in chat.

### Chat mode

1. Print **entire** compact message in **one** plain code fence.
2. Tell user: copy into MS Teams / Slack.
3. No `.md` file.

---

## Constraints

- **Parse first** — natural language OK; only stop when output mode or tag range still missing after parse
- **Partial input** — acknowledge what was found; ask for missing piece + accepted prompt examples
- **No silent defaults** for output mode or tag range
- **Jira URL** — key in merge → URL in output when `JIRA_BASE_URL` or URL in commit; verify before deliver
- **Chat mode** — merge changelog only; double newline after title
- **File mode** — full deploy-focused sections
- **No Contributors section**
- **No secrets** in output

---

## Git Commands Reference

```bash
git tag --sort=-version:refname | head -5
git log {FROM}..{TO} --merges --oneline
git diff {MERGE_SHA}^1..{MERGE_SHA}^2 --stat
git log -1 --format="%s%n%b" {MERGE_SHA} | grep -oE 'https://[a-zA-Z0-9.-]+\.atlassian\.net/browse/[A-Z][A-Z0-9]+-[0-9]+'
```
