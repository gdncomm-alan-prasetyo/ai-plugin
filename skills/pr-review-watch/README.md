# PR Review Watch — User Guide

Watches configured GitHub repos (or specific PR numbers) for new/updated open PRs, reviews diffs, posts review comments via `gh`. Personal automation — each teammate configures own repo list, locally, per machine.

**Manual-only** — runs only via `/pr-review-watch` or explicit request naming this skill. Never auto-triggers from natural-language "review my PR" requests — those route to `/review`.

## Review engine

| Repo type | Engine | Notes |
|---|---|---|
| Spring Boot (`pom.xml`/`build.gradle` at root) | `be-code-reviewer`, diff-only standalone mode by default | Same Verdict + 12-domain rubric as `/review` |
| Spring Boot, diff touches shared methods / Kafka / migrations / validation | Escalates to full `spring-review-smart` pipeline | Clones repo to `~/.claude/pr-review-watch/checkouts/`, builds `.review-context.md`, runs caller/downstream analysis |
| Other stacks | Generic defect scan | No Verdict/Risk system — Spring-only rubric |

Findings post as individual inline comments on their exact file/line (via the GitHub reviews API), not one bundled block — so each finding gets a real **Reply** button and you can thread a conversation on it. A short summary (Verdict + Overall Risk) posts alongside as the review body; findings without a single clear line fall back to a bullet there. Every submission is `event: COMMENT` — **never** `APPROVE` or `REQUEST_CHANGES`, even on a clean `✅ Approve` verdict. A human still has to click the real Approve button.

Repo-list mode never reviews your own PRs — skipped at listing time alongside drafts, same as a human reviewer wouldn't review their own work. Naming your own PR directly (`owner/repo#123`) still reviews it, since you asked for that one explicitly.

## Build status

Does **not** check Jenkins. Reviews whatever diff is on the PR regardless of build state — every cycle's report carries a reminder to confirm the build is green for the head commit before trusting the review.

## Setup (one-time, per machine)

```bash
gh auth login
gh auth status   # verify
```

Then either:
- Run `/pr-review-watch` once in normal interactive session — asks which repos to watch, saves answer.
- Or hand-create config file:

```jsonc
// ~/.claude/pr-review-watch/repos.json
["gdncomm/service-a", "gdncomm/service-b"]
```

## Usage

```
/pr-review-watch                          # configured repos, loops with adaptive pacing (default)
/pr-review-watch owner/repo owner/repo2   # override repos, adaptive pacing (default)
/pr-review-watch --every 10m              # configured repos, force fixed 10-min loop instead
/pr-review-watch --once                   # configured repos, single check, no loop
/pr-review-watch owner/repo#123           # one specific PR, single check, no loop, no repos.json needed
/pr-review-watch owner/repo#123 --loop    # opt into adaptive-paced looping on that one PR too
/pr-review-watch owner/repo#123 --loop 5m # opt into fixed 5-min looping on that one PR instead
```

**Repo-list mode loops by default** — running `/pr-review-watch` with no `--once` self-invokes the `loop` skill in dynamic self-pacing mode. Reviewed or replied to something → checks again in ~15 min; nothing changed or no open PRs → backs off to ~30 min. Force a flat cadence with `--every <Nm>` if preferred. Runs only while the session stays open — closing it stops the loop, same as any `/loop`; no OS-level persistence.

**PR-target mode** (`owner/repo#123`) is single-shot by default instead — skips repo-wide listing, works with zero setup, good for a one-off "review this PR" ask. Add `--loop [Nm]` to also watch that one PR on a recurring cadence.

## Per-cycle status report

Every cycle (including each loop tick) posts a status table in the session — not just GitHub comments:

```
## PR Watch — 2026-08-10 14:35

⚠️ Build status not checked — confirm Jenkins is green for each head commit before trusting a review below.

| Repo | Open PRs | Reviewed this cycle | Waiting (no changes) | Auto-replied | Needs human input | Errors |
|---|---|---|---|---|---|---|
| gdncomm/loyalty | 3 | 1 | 2 | 1 | 0 | 0 |
| gdncomm/member | 2 | 1 | 1 | 0 | 1 | 0 |
| **Total** | **5** | **2** | **3** | **1** | **1** | **0** |

Reviewed this cycle: gdncomm/loyalty#42: fix redemption bug — ⚠️ Approve with comments (diff-only)
Auto-replied: gdncomm/loyalty#42 (@alex): "why flag this null check" — replied
Needs human input: gdncomm/member#7 (@sam): "can we skip this validation for legacy accounts" — https://github.com/gdncomm/member/pull/7#discussion_r123
Own PRs excluded: 1
Next check: in 15m
```

"Waiting" = open PRs with no new commits since last check — nothing to do, just counted so you can see the loop is alive and current. This is separate from the review findings themselves, which still go to GitHub as PR comments, not into this table.

## Follow-up comment handling

Every cycle also checks for new PR comments since last check — even PRs with no new commit. Only comments addressed to the bot's own review count; unrelated human discussion is ignored. Since findings post as inline comments (see above), this is mostly real GitHub thread replies on a specific finding — plus, as a fallback, a general PR comment that clearly answers the bot's last post.

- **Plain technical question** about a finding it already posted (why flagged, does an existing annotation cover it, asks for the fix inline) → auto-replies directly in the thread.
- **Business or high-stakes call** (product/scope trade-off, priority override, security-exception approval, real technical disagreement) → never posts anything, surfaces it in the cycle's report instead (`Needs human input` column/line) so you reply yourself. Uncertain calls default here too.

A flagged comment is reported once, not every cycle — a new reply in the same thread gets picked up fresh.

## Config & state — per-user, not committed to this repo

| File | Purpose |
|---|---|
| `~/.claude/pr-review-watch/repos.json` | JSON array of `"owner/repo"` strings watched |
| `~/.claude/pr-review-watch/state.json` | Per PR: last-reviewed commit SHA, last-seen comment id, already-flagged comment ids — prevents duplicate reviews and duplicate replies/reports |

## Unattended / headless runs

`repos.json` missing → unattended run (`claude -p`, cron, Task Scheduler) can't answer prompt, skips cycle, reports "no repos configured." Set up `repos.json` first (see Setup above) before scheduling outside interactive session.

## Troubleshooting
- No comments posting → check `gh auth status`.
- Repo 404 / access denied → confirm access; entry stays in `repos.json`, error surfaces each run until fixed or removed.
- Disk filling up → `~/.claude/pr-review-watch/checkouts/` holds one clone per repo that ever escalated to full pipeline. Delete freely, re-clones on next escalation.

## Duplicate-review protection

`state.json` is the fast path — new session picks it up, skips already-reviewed commits, no re-review. If it's ever lost, deleted, or a prior run died between posting a comment and recording state, every posted review carries a hidden marker (`<!-- pr-review-watch: reviewed-at {sha} -->`) in the comment body. Before reviewing, the skill checks GitHub's own review list for that marker first — so a lost `state.json` just gets resynced, never causes a duplicate comment.

## Human-comment dedup

Before posting, the skill pulls existing PR comments/reviews (excluding its own account) and drops any finding a teammate already raised at the same file/nearby line, even from an earlier commit. It never restates what's already in the thread — if every finding is already covered, it posts nothing at all.

## Version
- 1.8 — 2026-08-10 — Removed Jenkins gate entirely — reviews regardless of build status, every report reminds user to confirm build is green
- 1.7 — 2026-08-10 — Adaptive-paced loop by default instead of flat 5-min interval — backs off once quiet, force fixed cadence with `--every`/`--loop <Nm>`
- 1.6 — 2026-07-23 — Jenkins gate: skips review until Jenkins build for PR's exact head commit is green, checked directly against Jenkins (not GitHub's Checks API)
- 1.5 — 2026-07-21 — Fixed bug where a genuinely new comment could get silently swallowed as "pre-existing history" on a PR's first tracked cycle; now compares against the bot's own last review timestamp instead of blanket-skipping
- 1.4 — 2026-07-21 — Repo-list mode skips PRs authored by current `gh` user; explicit PR-targets still review self-authored PRs
- 1.3 — 2026-07-21 — Findings post as individual inline (line-anchored) comments instead of one bundled review body, so each gets a real GitHub Reply/thread button
- 1.2 — 2026-07-21 — Follow-up comment detection: auto-replies to plain technical questions on its own findings, surfaces business/high-stakes comments for human reply instead of posting
- 1.1 — 2026-07-20 — Repo-list mode loops every 5 min by default (self-invokes `loop` skill); `--once`/`--every`/`--loop` flags added
- 1.0 — 2026-07-20 — Initial release
