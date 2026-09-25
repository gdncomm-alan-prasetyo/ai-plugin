---
name: team-pr-review
description: Manual-only. Invoke ONLY via explicit `/team-pr-review` command or when user explicitly names "team-pr-review". One command reviews open PRs across the user's fixed IAM/team repo list (gdncomm/cas, gdncomm/auth, gdncomm/iam-api, gdncomm/iam-session-manager, gdncomm/loyalty, gdncomm/member, gdncomm/pyeongyang-whatsapp), skipping any PR whose base branch is `master`, by delegating the surviving PRs to `pr-review-watch` — no `repos.json` setup needed, no need to type the repo list every time. Never auto-invoke from natural-language "review my PR" requests — those route to `/review`.
---

# Team PR Review

Wrapper around `pr-review-watch` for a fixed repo set, with one added exception: PRs targeting `master` are never reviewed.

`pr-review-watch` itself has no base-branch filter, so this skill does its own PR listing per repo, drops master-targeted PRs (and, since that means bypassing `pr-review-watch`'s own repo-list listing step, replicates its draft/own-PR/`--author` filtering too), then hands the survivors to `pr-review-watch` as explicit PR targets.

## Repo list (fixed)

```
gdncomm/cas
gdncomm/auth
gdncomm/iam-api
gdncomm/iam-session-manager
gdncomm/loyalty
gdncomm/member
gdncomm/pyeongyang-whatsapp
```

If the user asks to add/remove a repo from this set, edit this list in this file directly (not `~/.claude/pr-review-watch/repos.json` — that's a separate, unrelated config this skill doesn't use).

## Excluded base branches (fixed)

```
master
```

PRs whose base branch is in this list are skipped entirely — never listed to `pr-review-watch`, never reviewed, never reported as an error. If the user asks to exclude another base branch (e.g. `main`, a release branch), add it here.

## Args

Same flag surface as `pr-review-watch`, applied by this skill before delegating (not passed through, since delegation switches to explicit PR-target mode — see Step 4):
- `--once` → single cycle, no loop.
- `--every <Nm>` → fixed-interval loop.
- `--loop` (no value) → adaptive-pacing loop (also the default with no flags at all).
- `--author <login>[,<login>...]` → keep only PRs from these authors.
- `--exclude-repo <owner/repo>[,...]` → drop these repos from this run's fixed list.

## Step 0 — Loop dispatch

This skill owns its own loop rather than deferring to `pr-review-watch`'s Step 0, because the PR list must be re-listed and re-filtered (master-target exclusion) fresh every cycle — `pr-review-watch`'s repo-list loop mode assumes it does its own listing per repo, which we're bypassing.

- `--once` present → no loop. Continue to Step 1.
- `--every <Nm>` present → fixed loop: `Skill(skill: loop, args: "{Nm} /team-pr-review --once {--author/--exclude-repo flags if any}")`. Report once, then stop — do not run Steps 1–5 inline.
- Neither `--once` nor `--every` (this includes bare `--loop` and no flags at all) → adaptive loop: `Skill(skill: loop, args: "/team-pr-review --once {--author/--exclude-repo flags if any}")`. Report once, then stop — do not run Steps 1–5 inline.

Report text for either loop start: "Starting recurring team PR watch ({every {Nm} | adaptive pacing}) across the 7 fixed repos. Skips PRs targeting master. Does NOT check Jenkins build status — confirm green yourself before trusting a review. Stop anytime like any other `/loop`. Single check without looping: `/team-pr-review --once`."

## Step 1 — List open PRs per repo

For each repo in the fixed list (minus any `--exclude-repo` this run):
```
gh pr list --repo <owner/repo> --state open --json number,title,url,baseRefName,isDraft,author,headRefOid
```
Repo 404s / access denied → note as an error for Step 6's report, continue with the rest — don't abort the whole cycle.

## Step 2 — Filter

Drop, per PR, in this order:
1. `baseRefName` in the excluded-base-branches list above (`master`) — the new exception. Tally into a **Skipped (base = master)** bucket, no error, no review.
2. `isDraft: true` — not for review (same default `pr-review-watch` applies at its own Step 2).
3. `author.login` == current user (`gh api user --jq .login`) — own work, not for review.
4. `--author` given this run → also drop anything whose `author.login` isn't in that list.

Survivors continue to Step 3.

## Step 3 — Build PR-target list

For each survivor, form `owner/repo#<number>`. No survivors across all repos → skip Step 4, go straight to Step 6 with an empty "Reviewed" result.

## Step 4 — Delegate to pr-review-watch

```
Skill(skill: "pr-review-watch", args: "{survivor1} {survivor2} ... --once")
```
Explicit PR-targets bypass `pr-review-watch`'s own draft/own-PR/`--author` checks (already applied in Step 2) and its repo listing — it goes straight to diffing/reviewing each named PR. Always pass `--once` here regardless of this skill's own loop mode (Step 0 already owns any looping; a nested loop from `pr-review-watch` itself would double-schedule).

## Step 5 — (n/a)

Not used — Step 4's delegation and `pr-review-watch`'s own Step 13 per-PR reporting cover this.

## Step 6 — Report

Relay `pr-review-watch`'s per-PR output as-is (including its build-status-not-checked reminder), then append one line:

```
Skipped (base = master): {n} — {owner/repo#N, ... or "none"}
```

Plus, if any repos errored at Step 1: `Errors: {repo — reason}`.

## Notes

- The master-target exclusion is enforced here, not inside `pr-review-watch` — that skill is shared/reused as-is and stays untouched.
- Because filtering requires explicit PR-target delegation, this skill's loop is self-owned (Step 0) rather than relying on `pr-review-watch`'s repo-list loop — functionally equivalent (adaptive pacing by default, `--every` for fixed), just driven from this skill so the master-filter re-applies every cycle.
- Escalation to full pipeline, dedupe against human comments, state tracking, and follow-up-comment auto-reply are all `pr-review-watch`'s existing behavior per PR-target — unchanged.
- Does not read or write `~/.claude/pr-review-watch/repos.json` — this skill always builds its own PR-target list explicitly instead.
