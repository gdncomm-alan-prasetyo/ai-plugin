---
name: pr-fix-watch
description: Manual-only. Invoke ONLY via explicit `/pr-fix-watch` command or when user explicitly names "pr-fix-watch" / "PR fix watch skill". Never auto-invoke from phrases like "fix my PR", "address review comments" — needs explicit command. Counterpart to pr-review-watch: works only on PRs authored by current gh user. Does NOT check Jenkins build status — finds new reviewer comments, classifies each as actionable fix / question / disagreement, implements fixes via project's own dev/review skills where domain match exists, commits and pushes directly to PR branch after local build/tests pass, replies confirming fix. Disagreed comments get direct technical counter-reply; business/high-stakes disagreements held and surfaced to human instead of posted. Every report reminds the user to confirm the build is green before relying on this.
---

# PR Fix Watch

**Manual-only skill.** Activates only on explicit `/pr-fix-watch` command or user explicitly naming it — never from natural-language "fix my PR" / "address these comments" requests.

Counterpart to `pr-review-watch` — same mechanics, opposite direction. `pr-review-watch` reviews other people's PRs, skips own. `pr-fix-watch` fixes own PRs, skips everyone else's. Watches own open PRs for new reviewer comments, applies fixes directly (push to PR branch), or replies with technical counter-argument on disagreement. Does NOT check or fix Jenkins build status — reviewer-comment fixes only. User's job to confirm the build's green; every report reminds them (Step 9). Repo-list mode loops with adaptive pacing by default (Step 0) — backs off once quiet (Step 9b). PR-target mode runs once unless `--loop` given.

## Config & state — per-user, outside this repo

Never store these inside `skills/pr-fix-watch/` — installer force-copies this folder on every sync, wipes local edits. Keep them here instead:

- Repo list: shared with `pr-review-watch` — `~/.claude/pr-review-watch/repos.json`. Same repos, opposite direction (fixing here vs. reviewing there) — one list to maintain.
- Fix state: `~/.claude/pr-fix-watch/state.json` — JSON object mapping `"owner/repo#<PR number>"` to `{ "lastCommentId": <highest comment id processed>, "flaggedCommentIds": [<comment ids surfaced to user as business/high-stakes, not re-flagged>] }`.
- Local checkouts: `~/.claude/pr-fix-watch/checkouts/<owner>__<repo>/` — separate from `pr-review-watch`'s own checkout dir, avoids branch-state collisions if both skills run concurrently. Reused across cycles via `git fetch`, not deleted after use.

## Args
- (none) → repos from shared `repos.json`, all own open PRs. Loops with adaptive pacing by default — backs off when quiet (Step 9b). Force fixed cadence with `--every <Nm>`, disable loop with `--once`.
- `owner/repo [owner/repo ...]` → one-off repo-list override, own open PRs only. Same default adaptive-loop behavior.
- `owner/repo#<number> [...]` → target specific PR(s) directly. Must be authored by current user — checked before any action. Not own PR named explicitly → report and skip, never fix/reply on someone else's PR. Single-shot default, opt in with `--loop` (adaptive) or `--loop <Nm>` (fixed).
- `--org <owner>` → user-first search mode: find own open PRs across whole org via `gh search prs --author <self> --owner <owner> --state open`, no repo list needed — new repos auto-picked-up. Author fixed to self (`gh api user --jq .login`) — fix-watch only ever touches own PRs. Presence of `--org` switches Step 2 from per-repo listing to org search.
- `--exclude-repo <owner/repo>[,...]` → user-first mode only: drop these repos from search results. Ignored in repo-list mode.
- `--once` → force single cycle, no loop, even repo-list mode.
- `--every <Nm>` → repo-list mode only, force fixed interval instead of adaptive pacing.
- `--loop [Nm]` → PR-target mode only, opt into looping. No `Nm` → adaptive pacing (Step 9b). `Nm` given → fixed interval.
- Meta flags (`--once`, `--every`, `--loop`) and filter flags (`--org`, `--exclude-repo`, with values) stripped before parsing repo/PR targets.

## Step 0 — Loop dispatch (before Step 1)

Same decision as `pr-review-watch`:
- `--once` present → no loop, continue to Step 1.
- PR-target(s), no `--loop` → no loop (single-shot default). Continue to Step 1.
- PR-target(s) with `--loop <Nm>` → fixed loop, interval = `Nm`.
- PR-target(s) with `--loop` (no `Nm`) → adaptive loop.
- No PR-targets, no `--once`, `--every <Nm>` given → fixed loop, interval = `Nm`.
- No PR-targets, no `--once`, no `--every` → adaptive loop (default).

**Should loop (fixed)**: `Skill(skill: loop, args: "{interval} /pr-fix-watch --once {original repo/PR targets + filter flags (--org/--exclude-repo), if any}")`. `--once` baked into recurring call — every tick runs single cycle, never re-enters Step 0, loops never nest. Report once: "Starting recurring PR fix watch — every {interval}: {targets, or 'configured repo list'}. Applies fixes directly to your own PR branches, replies to reviewers. Does NOT check Jenkins build status — confirm the build is green yourself. Stop anytime like any other `/loop`. Single check: `/pr-fix-watch --once`." **Stop here — do not run Steps 1–9 inline.**

**Should loop (adaptive)**: `Skill(skill: loop, args: "/pr-fix-watch --once {original repo/PR targets + filter flags (--org/--exclude-repo), if any}")` — no interval, dynamic self-pacing mode. Report once: "Starting recurring PR fix watch — adaptive pacing, backs off once quiet: {targets, or 'configured repo list'}. Applies fixes directly to your own PR branches, replies to reviewers. Does NOT check Jenkins build status — confirm the build is green yourself. Stop anytime like any other `/loop`. Single check: `/pr-fix-watch --once`." **Stop here — do not run Steps 1–9 inline.** Each subsequent tick runs Step 9b to pick its own next wake time — see there for the delay rule.

**Should not loop**: continue to Step 1.

## Steps

1. **Resolve targets** — split args into repo-targets and PR-targets, same as `pr-review-watch` Step 1. No args, no `repos.json` → ask which repos to watch (writes to same shared file `pr-review-watch` uses). Inside `/loop`, `claude -p`, cron, or Task Scheduler: skip cycle, report "No repos configured. Create `~/.claude/pr-review-watch/repos.json`..." — not a blocking prompt.

2. **List own open PRs** — resolve `<self-login>` once per cycle: `gh api user --jq .login`.
   - Repo-targets: `gh pr list --repo <owner/repo> --state open --author <self-login> --json number,title,url,headRefOid,headRefName,isDraft`.
   - PR-targets: `gh pr view <number> --repo <owner/repo> --json number,title,url,headRefOid,headRefName,author,isDraft`. `author.login != <self-login>` → report "not your PR — pr-fix-watch only touches PRs you authored, skipping" and drop it. Never fix or reply on a PR someone else owns, named explicitly or not.
   - **User-first mode (`--org`)**: `gh search prs --owner <org> --author <self-login> --state open --json repository,number,title,url,isDraft` — own open PRs across whole org. Drop `--exclude-repo` repos + drafts. Each → Step 3, keyed `owner/repo#number` from `repository.nameWithOwner`. Search returns no `headRefName`/`headRefOid` — fetch per PR before Step 5's push-safety check: `gh pr view <number> --repo <owner/repo> --json headRefName,headRefOid`. Author fixed to self — no self-authored check needed, search already scopes to own PRs.
   - No Jenkins gate — every open PR from this list goes straight to Step 3, regardless of build status.

3. **Find unaddressed reviewer comments** — pull comments/reviews newer than stored `lastCommentId`:
   ```
   gh api repos/<owner>/<repo>/issues/<number>/comments --jq '.[] | {id, user: .user.login, body, created_at}'
   gh api repos/<owner>/<repo>/pulls/<number>/comments --jq '.[] | {id, user: .user.login, body, path, line, diff_hunk, in_reply_to_id, created_at}'
   gh api repos/<owner>/<repo>/pulls/<number>/reviews --jq '.[] | {id, user: .user.login, body, state, submitted_at}'
   ```
   Drop self-authored (`user.login == <self-login>`) — own replies, own fix confirmations.

   No `lastCommentId` yet (first cycle) → don't blanket-skip. First run means nothing fixed yet — every outstanding comment/review is genuine pending work, not history to backfill.

   Inline comments only — check thread resolution before classifying, skip already-resolved threads (human or bot already marked addressed):
   ```
   gh api graphql -f query='{ repository(owner:"<owner>", name:"<repo>") { pullRequest(number:<number>) { reviewThreads(first:100) { nodes { isResolved comments(first:1) { nodes { id } } } } } } }'
   ```

4. **Classify each candidate**, independently:
   - **Actionable fix** — concrete, in-scope code change requested (bug, missing null check, wrong logic, style violation, missing test), enough context/confidence to implement correctly → Step 5.
   - **Question, not a fix** — asks why something was built a certain way, no code change implied → Step 6, answer path.
   - **Disagree / not suitable** — conflicts with existing codebase pattern, outside PR's scope, based on a misunderstanding, or confidence in the suggested fix too low to safely apply → Step 6, counter-reply path.
     - **Technical disagreement** (implementation detail, pattern preference, factual correction) → auto-counter-reply.
     - **Business or high-stakes call** (scope negotiation, priority override, "merge now follow up later," real product/security consequence) → Step 7, hold for human. Uncertain → default here.

5. **Apply fix** (actionable path):
   - Checkout: `~/.claude/pr-fix-watch/checkouts/<owner>__<repo>/` — `git clone` if missing, else `git fetch origin`. `gh pr checkout <number> --repo <owner/repo>` inside it.
   - Locate exact file/line from comment's `path`/`line`/`diff_hunk`. Read surrounding code before editing.
   - Prefer project's own dev skills over freehand edits where comment's domain matches one:
     - Missing/weak test coverage → `generate-tests` skill.
     - Formatting/style violation → apply `spring-review-code-formatter`'s BliBli Eclipse rules by hand (2-space indent, 100-char lines, K&R braces) — that skill reviews only, doesn't auto-fix.
     - Migration/index/expand-contract concern → follow `spring-review-migration-safety`'s rubric, don't reintroduce the flagged risk.
     - Idempotency/Kafka/Redis/security/query-performance concern → consult matching `spring-review-*` sub-skill's rubric (`~/.claude/references/domains.md`) as correctness bar, not just literal comment text.
     - No domain match → direct edit, following surrounding code's existing conventions.
   - No comment by default. Fix speaks for itself, commit message + reply already say what changed. Add one only for non-obvious WHY (hidden constraint, subtle invariant) — one line, no restating the diff or the reviewer's comment.
   - Build/test locally before committing — project's own build/test command (Maven for Spring repos). Fails → don't commit/push, fall back to Step 6's counter-reply with reason "attempted fix, local build/tests failed — needs manual review," tally **Needs human input**, not **Fixed**.
   - Passes → commit: `git commit -m "Address review feedback: <short description> (resolves <owner/repo>#<PR> comment #<commentId>)"`.
   - Push safety check: local checked-out branch must equal PR's `headRefName` from Step 2/3 — mismatch → abort, fall back to Step 7 (ref drift, needs human). Match → `git push origin HEAD:<headRefName>`. **Never** `--force`, **never** any branch but PR's own head.
   - Reply confirming fix: `gh api repos/<owner>/<repo>/pulls/<number>/comments -f body="<!-- pr-fix-watch: applied-fix-for {commentId} --> Fixed in {commit-sha}: <one-line what changed>" -F in_reply_to=<commentId>` for inline comments; `gh pr comment <number> --repo <owner/repo> --body "..."` when feedback has no single inline anchor (review-body-level).
   - Tally **Fixed & pushed** (Step 9).

6. **Reply without fix** (question or technical-disagreement path):
   - Durable check first: search PR comments for `<!-- pr-fix-watch: replied-to {commentId} -->` or `<!-- pr-fix-watch: countered {commentId} -->` — found → skip, already handled.
   - Question → post with marker `replied-to`, direct answer. Tally **Answered**.
   - Technical disagreement → post with marker `countered`, body explains concretely why the suggestion isn't applied (what it'd break, why current approach intentional, or why out of scope) — never a bare "won't fix." Tally **Countered**.

7. **Hold for human** (business/high-stakes, or push-safety abort from Step 5): no post. Tally **Needs human input** (author + one-line paraphrase). Add `commentId` to `flaggedCommentIds` — surfaces once, not every cycle; new reply in same thread picked up fresh.

8. **Update state** — after handling every candidate this cycle: write `lastCommentId` (max seen, acted on or not) and `flaggedCommentIds` into `~/.claude/pr-fix-watch/state.json`.

9. **Report** — repo-list runs: status table every cycle.
   ```
   ## PR Fix Watch — {timestamp}

   ⚠️ Build status not checked — confirm Jenkins is green before relying on these fixes.

   | Repo | Own Open PRs | Fixed & pushed | Answered | Countered | Needs human input | Errors |
   |---|---|---|---|---|---|---|
   | {owner/repo} | {n} | {n} | {n} | {n} | {n} | {n} |
   | **Total** | **{n}** | **{n}** | **{n}** | **{n}** | **{n}** | **{n}** |

   Fixed & pushed: {for each — "owner/repo#N: {comment paraphrase} — fixed in {sha}", or "none"}
   Answered: {for each — "owner/repo#N (@reviewer): {question paraphrase} — replied", or "none"}
   Countered: {for each — "owner/repo#N (@reviewer): {suggestion paraphrase} — countered, reason: {short reason}", or "none"}
   Needs human input: {for each — "owner/repo#N (@reviewer): {one-line paraphrase} — {comment url}", or "none"}
   Errors: {repo/PR + reason, if any}
   Next check: in {interval} — or "single run, not looping" for `--once`
   ```
   Explicit PR-target runs: show full result directly, plus the same build-status reminder line, no table.

9b. **Pace next check (adaptive loop only)** — skip for fixed-interval loops (`--every`/`--loop <Nm>` — `loop` skill reschedules itself) and single-shot runs. Adaptive loop ends each tick by picking own next wake time, not flat interval — call `ScheduleWakeup` with same `/pr-fix-watch --once {targets + filter flags}` prompt:
    - Fixed/replied/countered something this cycle → `delaySeconds` 900. Recent activity, worth checking back reasonably soon for fast-follow comments.
    - Nothing changed, or no open PRs at all → `delaySeconds` 1800. Report notes watch is idle, can stop if nothing expected soon.
    `reason` names what's being waited on (e.g. "owner/repo#42 fix pushed, watching for follow-up").

## Notes

- Never touches a PR not authored by current `gh` user — checked before any listing/action, both repo-list and explicit PR-target modes. Opposite of `pr-review-watch`, which skips only own PRs.
- **Two scoping models.** Repo-list (default): repos.json/args, own PRs per listed repo. User-first (`--org gdncomm`): `gh search prs` for own PRs across whole org, `--exclude-repo` denylist subtracts repos — no repo list to maintain, new services auto-picked-up. Author always fixed to self in both — `--org` never widens past own PRs.
- Never force-pushes, never pushes to any branch but the PR's exact head branch, never merges, never resolves/dismisses a review thread itself.
- Fix only committed/pushed after local build/tests pass — failed validation falls back to **Needs human input**, never a broken push.
- **Does not check or fix Jenkins build status** — no gate, no auto-diagnose, no auto-fix for red builds. Reviewer-comment fixes only. Every report (Step 9) reminds the user to confirm the build is green before relying on these fixes.
- Loop mechanics, dedup markers, durable state-loss recovery (search GitHub comments for own marker before re-acting) — same pattern as `pr-review-watch`.
- Iterates naturally with `pr-review-watch` running under a teammate's identity: they review → this skill fixes and pushes → new commit triggers their next review cycle (new `headRefOid`) → further comments handled next `pr-fix-watch` cycle. Expected, not a bug.
- Repo 404 or access denied → report, continue with rest, don't abort whole cycle.
- Requires `gh` CLI authenticated with push access to target repos (`gh auth status`).
