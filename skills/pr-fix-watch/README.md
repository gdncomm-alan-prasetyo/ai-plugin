# PR Fix Watch — User Guide

Watches your own open GitHub PRs (or specific PR numbers) for new reviewer comments, applies fixes directly to PR branch, or replies with technical counter-argument when it disagrees. Counterpart to `pr-review-watch` — that skill reviews others' PRs, skips own; this one fixes own PRs, skips everyone else's.

Does **not** check Jenkins build status — reviewer-comment fixes only. Confirm the build's green yourself; every cycle's report carries a reminder.

**Manual-only** — runs only via `/pr-fix-watch` or explicit request naming this skill. Never auto-triggers from "fix my PR" / "address these comments" style requests.

## What it does per comment

| Comment type | Action |
|---|---|
| Actionable fix suggestion, in scope, high confidence | Implements fix, runs local build/tests, commits, pushes to PR branch, replies with commit link |
| Question (not a fix request) | Replies directly with an answer, no code change |
| Technical disagreement (pattern preference, factual correction, would break something) | Replies with reasoning for not applying it — never a bare "won't fix" |
| Business/high-stakes call (scope, priority, security trade-off) | Never posts — surfaces in the cycle report for you to reply yourself |
| Fix attempted but local build/tests fail | No push — surfaces in **Needs human input** instead |

Already-resolved GitHub review threads are skipped — no reprocessing what's already marked addressed.

## Setup (one-time, per machine)

```bash
gh auth login
gh auth status   # verify — needs push access to target repos
```

Shares the repo list with `pr-review-watch`:

```jsonc
// ~/.claude/pr-review-watch/repos.json
["gdncomm/service-a", "gdncomm/service-b"]
```

If you've already set up `pr-review-watch`, this skill reuses that same file — nothing else to configure.

## Usage

```
/pr-fix-watch                          # own PRs across configured repos, loops with adaptive pacing (default)
/pr-fix-watch owner/repo owner/repo2   # override repos, adaptive pacing (default)
/pr-fix-watch --every 10m              # configured repos, force fixed 10-min loop instead
/pr-fix-watch --once                   # configured repos, single check, no loop
/pr-fix-watch owner/repo#123           # one specific PR (must be yours), single check, no loop
/pr-fix-watch owner/repo#123 --loop    # opt into adaptive-paced looping on that one PR too
/pr-fix-watch owner/repo#123 --loop 5m # opt into fixed 5-min looping on that one PR instead
```

Naming a PR you don't own (`owner/repo#123` where you're not the author) → reported and skipped, never touched.

**Repo-list mode loops by default** — same mechanism as `pr-review-watch`, dynamic self-pacing. Fixed/replied/countered something → checks again in ~15 min; nothing changed or no open PRs → backs off to ~30 min. Force a flat cadence with `--every <Nm>` if preferred. Runs only while the session stays open.

## Per-cycle status report

```
## PR Fix Watch — 2026-08-10 14:35

⚠️ Build status not checked — confirm Jenkins is green before relying on these fixes.

| Repo | Own Open PRs | Fixed & pushed | Answered | Countered | Needs human input | Errors |
|---|---|---|---|---|---|---|
| gdncomm/loyalty | 2 | 1 | 1 | 0 | 0 | 0 |
| gdncomm/member | 1 | 0 | 0 | 1 | 1 | 0 |
| **Total** | **3** | **1** | **1** | **1** | **1** | **0** |

Fixed & pushed: gdncomm/loyalty#51: add null check on redemption amount — fixed in a1b2c3d
Answered: gdncomm/loyalty#51 (@sam): "why not use Optional here" — replied
Countered: gdncomm/member#96 (@alex): "switch to synchronous call" — countered, reason: breaks existing async contract
Needs human input: gdncomm/member#96 (@alex): "can we drop this validation for legacy accounts" — https://github.com/gdncomm/member/pull/96#discussion_r456
Next check: in 15m
```

## Safety rails

- Never pushes to a PR you don't own.
- Never force-pushes, never pushes to any branch but the PR's own head branch.
- Never merges a PR, never resolves or dismisses a review thread itself.
- Commits only after local build/tests pass — a failing fix never gets pushed, it surfaces as **Needs human input** instead.

## Config & state — per-user, not committed to this repo

| File | Purpose |
|---|---|
| `~/.claude/pr-review-watch/repos.json` | Shared repo list (same file `pr-review-watch` uses) |
| `~/.claude/pr-fix-watch/state.json` | Per PR: last-processed comment id, already-flagged comment ids |
| `~/.claude/pr-fix-watch/checkouts/<owner>__<repo>/` | Local clone used to apply fixes — separate from `pr-review-watch`'s own checkout dir |

## Interaction with pr-review-watch

Designed to iterate with a teammate running `pr-review-watch` under their own identity against your PR: they review → `pr-fix-watch` fixes and pushes → new commit triggers their next review cycle (new head commit) → further comments handled next `pr-fix-watch` cycle. Expected, not a loop bug — each skill only acts on comments/commits it hasn't seen yet.

## Version
- 1.2 — 2026-08-10 — Confirmed no Jenkins check — reviewer-comment fixes only, every report reminds user to confirm build is green
- 1.1 — 2026-08-10 — Adaptive-paced loop by default instead of flat 5-min interval — backs off once quiet, force fixed cadence with `--every`/`--loop <Nm>`
- 1.0 — 2026-07-23 — Initial release
