# Release Notes Template

---

## Markdown File Template

`{PROJECT_NAME}-RELEASE-NOTES-{version}.md`

```markdown
# {PROJECT_NAME} — Release {VERSION_DISPLAY}

**Project:** {PROJECT_NAME}  
**Tag range:** `{FROM_TAG}` → `{TO_TAG}`  
**Release date:** {YYYY-MM-DD}  
**Commits:** {N} ({K} feature merges) · **Files changed:** {M}

---

## Highlights

{2–4 sentences. Production logic + deploy-critical config/system_parameter. No tests.}

---

## What's New

{Production code / API / UI only.}

### {Feature theme}

- {Capability change}

---

## Bug Fixes

- **{Area}:** {runtime fix}

---

## Improvements

{Production logic only. Omit section if empty.}

- {Logic improvement}

---

## Breaking Changes

None — backward-compatible with `{FROM_TAG}`.

{Or breaking items with action required.}

---

## Configuration & System Parameters

{Required when CONFIG / SYSTEM_PARAM changed. Omit if none.}

> **Before deploy:** verify / add every row below.

| Key / Parameter | Default | Required | Notes |
|-----------------|---------|----------|-------|
| `feature.x.enabled` | `false` | No | {note} |
| `system_parameter.NAME` | `value` | Yes | insert before deploy |

---

## Merged Work

Feature merges only. Branch sync excluded.

| Author | Branch / PR | Jira | Summary |
|--------|-------------|------|---------|
| {Name} | `feature/foo` / PR #123 | `https://gdncomm.atlassian.net/browse/IAM-456` | {summary} |
| {Name} | PR #124 | `https://gdncomm.atlassian.net/browse/IAM-789` | {summary} |
| {Name} | `fix/bar` | — | {no key in commit} |

**Jira column — mandatory:**

| Case | Cell value |
|------|------------|
| Full URL in merge commit | exact URL from commit |
| Key + `JIRA_BASE_URL` known | `https://host.atlassian.net/browse/{KEY}` — **always print** |
| Key only, base unknown | key text |
| No key | `—` |

Never leave Jira cell empty when key was extracted.

---

## For Operators

{Migrations / deps only. Config duplicated above → skip here.}

---

## Technical Appendix

{Optional. Test changes go here only.}
```

---

## Chat Compact Template

MS Teams / Slack. **Merge changelog only.** No other sections.

```
**{PROJECT_NAME} — Release {VERSION_DISPLAY}**
{FROM_TAG} → {TO_TAG} · {YYYY-MM-DD}


**Changelog**
• {Author} · {branch or PR #N} · https://gdncomm.atlassian.net/browse/IAM-123 — {summary}
• {Author} · PR #124 · https://gdncomm.atlassian.net/browse/IAM-456 — {summary}
• {Author} · feature/retry — {summary, no Jira key}
```

### Chat rules

| Rule | Detail |
|------|--------|
| Content | **Merge commits only** — no Highlights / Fixes / Deploy blocks |
| Title spacing | **Two empty lines** after title block before `**Changelog**` |
| Section spacing | One empty line after `**Changelog**` before first bullet |
| Jira | Key in merge → **full URL on bullet line** (mandatory when base known) |
| Bullets | `•` one merge per line |
| No tables | Never |

### Chat example

```
**iam-service — Release v2.3.0**
v2.2.0 → v2.3.0 · 2026-07-10


**Changelog**
• Alvin · PR #892 · https://gdncomm.atlassian.net/browse/IAM-100 — bulk point transfer
• Budi · feature/retry-acquire · https://gdncomm.atlassian.net/browse/IAM-101 — acquire retry logic
• Citra · fix/null-checkout — null member ID handling
```

---

## Validation Reply Template

Friendly stop when input still incomplete after parsing. **Always** include accepted prompt examples.

```
I can generate release notes once two things are clear:

**Still need:** {output mode | tag range | both}
{**Already got:** {parsed part} — if any}

**Accepted prompts** (copy and adjust):

• release notes md file from v2.1.0 to v2.3.0
• write changelog for ms teams from v2.1.0 to v2.3.0
• slack release notes from previous to current
• markdown release notes between v1.0.0 and v2.0.0

**Tag tips:** two tags (`from X to Y`) or `previous to current`.
**Output tips:** `md file` / `markdown` OR `teams` / `slack` / `compact chat`.
```
