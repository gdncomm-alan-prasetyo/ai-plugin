---
name: pr-review-watch
description: Manual-only. Invoke ONLY via explicit `/pr-review-watch` command or when user explicitly names "pr-review-watch" / "PR watch skill". Never auto-invoke from general phrases like "review my PR", "check this PR", "review this repo" — those route to the standard /review flow instead. When invoked, checks configured repos or specific PR numbers for new/updated open PRs, reviews diffs via be-code-reviewer / spring-review-smart (Spring Boot repos) or generic scan (other repos), posts review comments via gh. Does NOT check Jenkins build status — every report reminds the user to confirm the build is green for the head commit before trusting the review. Also watches for follow-up PR comments after a review, even with no new commit — auto-replies to plain technical questions about its own findings, surfaces business or high-stakes calls to the human instead of posting.
---

# PR Review Watch

**Manual-only skill.** Activates only on explicit `/pr-review-watch` command or user explicitly naming it — never from natural-language PR/review requests (those are `/review`'s job).

Personal PR-watch automation. Each cycle: find new/updated open PRs (configured repos, or specific PR numbers given directly), review diff, post review comment via `gh`, record state so unchanged PRs skip re-review next cycle. Does NOT check Jenkins build status — reviews whatever diff is on the PR regardless of build state. User's job to confirm the build's green before trusting the review; every report reminds them (Step 13). Repo-list mode loops with adaptive pacing by default (Step 0) — backs off once quiet (Step 13b). PR-target mode runs once unless `--loop` given.

## Config & state — per-user, outside this repo

Never store these inside `skills/pr-review-watch/` — installer force-copies this folder on every sync, wipes local edits. Keep them here instead:

- Repo list: `~/.claude/pr-review-watch/repos.json` — JSON array of `"owner/repo"` strings.
- Review state: `~/.claude/pr-review-watch/state.json` — JSON object mapping `"owner/repo#<PR number>"` to an object: `{ "headRefOid": "<last-reviewed commit SHA>", "lastCommentId": <highest comment id seen>, "flaggedCommentIds": [<comment ids already surfaced to user, not re-flagged>] }`. Old flat-string format (`"owner/repo#N": "<sha>"`) still readable — treat as `{ headRefOid: <that string> }`, no comment tracking yet (see Step 3a).
- Escalated-review checkouts: `~/.claude/pr-review-watch/checkouts/<owner>__<repo>/` — local clone, created only when a PR escalates to full pipeline (Step 6). Reused across cycles via `git fetch`, not deleted after use.

## Args
- (none) → configured repo list, all open PRs. **Loops with adaptive pacing by default** — backs off when quiet (Step 13b). Force fixed cadence with `--every <Nm>`, disable loop with `--once`.
- `owner/repo [owner/repo ...]` → one-off repo-list override for this run, review all open PRs in each. Don't overwrite config unless user says remember them. Same default adaptive-loop behavior as above.
- `owner/repo#<number> [...]` → target specific PR(s) directly. Skips repo-wide listing (Step 2) and repo-list config entirely — works even with no `repos.json`. Mix freely with plain `owner/repo` args in same call. Single-shot by default (no loop) — opt in with `--loop` (adaptive) or `--loop <Nm>` (fixed).
- `--author <login>[,<login>...]` → review only PRs from these authors. Repo-first mode (no `--org`): filters Step 2's listing client-side, keeps only matching `author.login`, still drops drafts + own PRs. User-first mode (with `--org`): the authors searched for.
- `--org <owner>` → user-first search mode. Lists all open PRs by `--author` logins across whole org via `gh search prs`, no repo list needed — new repos auto-picked-up. Presence of `--org` switches Step 2 from per-repo listing to org search. Requires `--author`.
- `--exclude-repo <owner/repo>[,...]` → user-first mode only: drop these repos from search results (sandboxes, noisy repos). Ignored in repo-first mode.
- `--once` → force a single cycle this run, no loop starts, even in repo-list mode.
- `--every <Nm>` → repo-list mode only: force fixed interval instead of adaptive pacing (e.g. `--every 10m`).
- `--loop [Nm]` → PR-target mode only: opt into looping on that specific PR. No `Nm` → adaptive pacing (Step 13b). `Nm` given → fixed interval.
- Meta flags (`--once`, `--every`, `--loop`) and filter flags (`--author`, `--org`, `--exclude-repo`, with their values) stripped before parsing repo/PR targets — never treated as a target themselves.

## Step 0 — Loop dispatch (before Step 1)

Decide whether this run starts a recurring loop instead of running inline once:
- `--once` present → no loop. Continue to Step 1.
- PR-target(s) present, no `--loop` → no loop (PR-target default is single-shot). Continue to Step 1.
- PR-target(s) present with `--loop <Nm>` → fixed loop, interval = `Nm`.
- PR-target(s) present with `--loop` (no `Nm`) → adaptive loop.
- No PR-targets (repo-list mode: config or repo-args), no `--once`, `--every <Nm>` given → fixed loop, interval = `Nm`.
- No PR-targets, no `--once`, no `--every` → adaptive loop (default).

**Should loop (fixed)**: invoke `loop` skill — `Skill(skill: loop, args: "{interval} /pr-review-watch --once {original repo/PR targets + filter flags (--author/--org/--exclude-repo), if any}")`. Note the `--once` baked into the recurring call — every tick after this one runs a single cycle and stops there, never re-enters Step 0's loop-start logic, so loops never nest. Report once: "Starting recurring PR watch — every {interval}: {targets, or 'configured repo list'}. Dedupes against human comments and its own prior reviews each cycle. Does NOT check Jenkins build status — confirm the build is green yourself before trusting a review. Stop anytime like any other `/loop`. Single check without looping: `/pr-review-watch --once`." **Stop here — do not run Steps 1–13 inline.** The loop's own execution handles the first and all subsequent cycles.

**Should loop (adaptive)**: `Skill(skill: loop, args: "/pr-review-watch --once {original repo/PR targets + filter flags (--author/--org/--exclude-repo), if any}")` — no interval, dynamic self-pacing mode. Report once: "Starting recurring PR watch — adaptive pacing, backs off once quiet: {targets, or 'configured repo list'}. Dedupes against human comments and its own prior reviews each cycle. Does NOT check Jenkins build status — confirm the build is green yourself before trusting a review. Stop anytime like any other `/loop`. Single check without looping: `/pr-review-watch --once`." **Stop here — do not run Steps 1–13 inline.** Each subsequent tick runs Step 13b to pick its own next wake time — see there for the delay rule.

**Should not loop**: continue to Step 1 for a single cycle, as below.

## Steps

1. **Resolve targets** — split args (after stripping meta + filter flags) into repo-targets (`owner/repo`) and PR-targets (`owner/repo#<number>`).
   - Any PR-targets present → use as-is, go straight to Step 3 for each (skip Step 2's listing for these). Explicit wins over `--org`.
   - `--org <owner>` present (no PR-targets) → user-first search mode: skip repo list entirely, Step 2 runs org search. `--author` required — missing → report "user-first mode needs --author <login>", skip cycle.
   - Repo-targets from args → use as this run's repo list.
   - No args at all: `~/.claude/pr-review-watch/repos.json` exists and non-empty → load as repo list. Else ask user which repos to watch (`owner/repo` format), write answer to `repos.json` so future runs skip asking. Inside `/loop`, `claude -p`, cron, or Task Scheduler where prompt would stall: skip cycle, report exactly this — "No repos configured. Create `~/.claude/pr-review-watch/repos.json` with `[\"owner/repo\", ...]`, run `/pr-review-watch` once interactively, or target a specific PR with `/pr-review-watch owner/repo#123`. See `skills/pr-review-watch/README.md`." — not a blocking prompt.

2. **List open PRs** per repo-target:
   ```
   gh pr list --repo <owner/repo> --state open --json number,title,url,headRefOid,isDraft,author
   ```
   Skip draft PRs and PRs authored by current user (`author.login` == `gh api user --jq .login`) — own work, not for review. (PR-targets from Step 1 skip both checks — go straight to Step 3, reviewed even if draft or self-authored, since user named it explicitly.)

   `--author` given (repo-first) → also drop PRs whose `author.login` not in the list. Client-side filter after listing — non-matching PRs never reach review.

   **User-first mode (`--org`)** — replace per-repo listing with one org search:
   ```
   gh search prs --owner <org> --author <login> --state open --json repository,number,title,url,isDraft,author
   ```
   Multiple `--author` logins → one search per login (`gh search prs` takes one `--author`), or raw `gh api search/issues -f q='org:<org> is:pr is:open author:a author:b'`. Merge, dedupe by `repository.nameWithOwner` + number. Drop `--exclude-repo` repos, drafts, own PRs. Each survivor → Step 3, keyed `owner/repo#number` from `repository.nameWithOwner` (same key as repo-first). Search returns no `headRefOid` — Step 3 fetches it per PR via `gh pr view`, same as a PR-target.

3. **Diff against state** — load `~/.claude/pr-review-watch/state.json` (missing file = `{}`). For each PR (from Step 2 listing or a direct PR-target), fetch current `headRefOid` (`gh pr view <number> --repo <owner/repo> --json headRefOid,title,url,isDraft` for PR-targets and user-first search results), compare to stored `headRefOid` keyed by `owner/repo#number`. Either way, run Step 3a next before branching further. Equal → already reviewed at this commit. Repo-list PRs: skip review, tally into Step 13's **Waiting** bucket (no new commits since last check) — no per-PR chat noise, just counted. Explicit PR-targets: skip review but report "already reviewed at this commit — no changes" instead of silence, since user explicitly asked for it. Different or absent → needs review, continue to Step 4.

3a. **Follow-up comment check** — runs every cycle per PR, both branches of Step 3, before continuing. Catches comments posted since last check, even with no new commit.
    - Pull comments newer than stored `lastCommentId`:
      ```
      gh api repos/<owner>/<repo>/issues/<number>/comments --jq '.[] | {id, user: .user.login, body, created_at}'
      gh api repos/<owner>/<repo>/pulls/<number>/comments --jq '.[] | {id, user: .user.login, body, in_reply_to_id, created_at}'
      ```
      Filter to `id` greater than stored `lastCommentId` — every comment above it, not just the newest one.

      No stored value yet (PR never comment-tracked before, including old flat-string state entries) — don't blanket-skip, swallows a genuine new comment that happens to be first one seen. Instead: `gh api repos/<owner>/<repo>/pulls/<number>/reviews --jq '[.[] | select(.user.login=="<own login>")] | max_by(.submitted_at) | .submitted_at'` — own last review's timestamp.
      - No own review yet → nothing posted to follow up on. Blanket-skip correct here: set `lastCommentId` to current max id, no action.
      - Own review exists → split candidate comments by `created_at` vs that timestamp. At/before → pre-existing history, backfill only, no action. After → genuine follow-up, evaluate same as any other cycle below.

      Continue to Step 3's branch once actions (if any) done.
    - Drop own account's comments (`gh api user --jq .login`).
    - For each remaining comment, independently, decide addressed to bot: inline reply chain (`in_reply_to_id`, walked to root) lands on a comment the bot posted, or an issue comment clearly answering the bot's last review post (quotes a finding id, replies "your suggestion", etc.). Not addressed to bot → ignore, no action, no report line.
    - Each addressed-to-bot comment, classify on its own:
      - **Plain technical question** — self-contained, answerable from code + the original finding (why flagged, does an existing annotation already cover it, asks for the fix inline) → auto-reply eligible.
      - **Business or high-stakes call** — product/scope trade-off, priority override, security-exception approval, real technical disagreement with consequences → report-only, no post. Uncertain → default here.
    - Auto-reply path: durable check first — search PR comments for marker `<!-- pr-review-watch: replied-to {commentId} -->` (guards re-reply after state loss). Found → skip, already handled. Not found → post direct technical answer referencing the original finding: `gh api repos/<owner>/<repo>/pulls/<number>/comments -f body="<!-- pr-review-watch: replied-to {commentId} --> ..." -F in_reply_to=<commentId>` for inline threads, `gh pr comment <number> --repo <owner/repo> --body "..."` for issue-level. Tally into Step 13's **Auto-replied** bucket.
    - Report-only path: no post. Tally into Step 13's **Needs human input** bucket — author + one-line paraphrase. Add `commentId` to `flaggedCommentIds` so it surfaces once, not every cycle — a new reply in the same thread still gets picked up fresh (new comment id).
    - After processing: set `lastCommentId` to the max comment id seen this cycle (acted on or not) — written in Step 12.

4. **Durable duplicate check** — before reviewing, confirm GitHub itself has no review for this exact commit yet. Catches cases local state can't: `state.json` lost/deleted/never written, or a prior session that died between posting (Step 10) and recording state (Step 11).
   ```
   gh pr view <number> --repo <owner/repo> --json reviews --jq '.reviews[].body'
   ```
   Search results for marker `<!-- pr-review-watch: reviewed-at {headRefOid} -->` matching current `headRefOid`. Found → GitHub is source of truth over stale/missing local state: skip straight to Step 11 to resync `state.json` — don't re-review, don't re-post. Not found → continue to Step 5.

5. **Detect stack** — for each PR needing review: `gh api repos/<owner>/<repo>/contents/pom.xml` then `.../build.gradle` (root only). Either 200 → Spring Boot repo, go to Step 6. Both 404 → not Spring, go to Step 9.

6. **Diff-only review (Spring, default)** — `gh pr diff <number> --repo <owner/repo>`. Invoke `be-code-reviewer` agent, **standalone mode**, with: the diff, PR title/description, note it's a GitHub PR (no `.review-context.md`, no git commands available). Returns Verdict (`✅ Approve` / `⚠️ Approve with comments` / `🚫 Request changes`) + Overall Risk + 🔴/🟠/🟡 findings per 12-domain rubric (`~/.claude/references/domains.md`).

7. **Escalation check** — escalate to Step 8 (full pipeline) if diff matches ANY:
   - Service/repository method signature changed, method looks shared (public, non-trivial body) — downstream impact needs caller grep.
   - Kafka producer/consumer/listener changed, or Redis cache logic changed.
   - DTO validation annotations changed, enum values changed, or migration file added.
   - State-mutating endpoint or Kafka consumer changed (idempotency-relevant).
   - Step 6 result has a 🔴 Critical or 🟠 Major finding labeled *hypothesis* (be-code-reviewer flags its own uncertainty when it lacks cross-file context).
   None match → skip to Step 10 using Step 6's result as-is.

8. **Full pipeline (escalated)**:
   - Local clone at `~/.claude/pr-review-watch/checkouts/<owner>__<repo>/` — `git clone` if missing, else `git fetch origin` inside it.
   - `gh pr checkout <number> --repo <owner/repo>` inside that clone.
   - Run `be-review-context` skill in that directory to build `.review-context.md` (base = PR's base branch).
   - Run `spring-review-smart` on the cache → Principal Engineer synthesis (Verdict + Overall Risk + findings), same contract as Step 6's output. Use this instead of Step 6's result. Go to Step 10.

9. **Generic fallback (non-Spring)** — `gh pr diff <number> --repo <owner/repo>`. Read for real defects: correctness bugs, security issues (auth bypass, injection, secrets/PII exposure), broken tests, obvious regressions. No nitpicking minor style, no Verdict/Risk system (be-code-reviewer's rubric is Spring-specific). Skip trivial diffs (lockfiles, formatting-only).

10. **Dedupe against human comments** — before posting, drop findings a human already raised. Pull existing PR commentary:
    ```
    gh pr view <number> --repo <owner/repo> --json comments,reviews
    gh api repos/<owner>/<repo>/pulls/<number>/comments --jq '.[] | {user: .user.login, path, line, body}'
    ```
    Exclude own account (`gh api user --jq .login`) — own past reviews already handled by Step 4. For each candidate finding, judge semantically against remaining human comments/review threads: same file, same/nearby line, same underlying concern → already covered, even if raised on an earlier commit. Drop covered findings from the comment body — don't restate, don't summarize what's already visible in the thread above them. All findings covered → skip posting entirely (state update only, same treatment as a trivial diff) — nothing new to add.

11. **Post comment** — findings post as individual inline (line-anchored) review comments where possible, not one bundled block. Inline comments get GitHub's native Reply/thread button; a bundled body does not (Step 3a's `in_reply_to_id` detection depends on this).
    - No findings left after Step 10 (all trivial, or all covered by existing human comments) → skip comment, state update only (Step 4's marker check never sees this commit — harmless, worst case a repeat pass, never a duplicate post, since nothing was posted).
    - Otherwise split remaining findings into two groups: **locatable** (specific `file` + `line` from diff) → one inline comment each; **unlocatable** (cross-cutting/architecture-level, no single line) → bullet in summary body.
    - Build one JSON payload for single review submission — write to temp file first (`Write` tool), avoids shell-quoting markdown:
      ```json
      {
        "body": "<!-- pr-review-watch: reviewed-at {headRefOid} -->\n**Verdict:** {verdict}\n**Overall Risk:** {level}\n_Reviewed via: {diff-only|full pipeline}_\n\n{any unlocatable findings as bullets, or 'All findings below inline.'}",
        "event": "COMMENT",
        "comments": [
          { "path": "src/main/java/Foo.java", "line": 42, "side": "RIGHT", "body": "**[severity] Title** — what/why/fix" }
        ]
      }
      ```
      `side: "RIGHT"` for added/changed lines (default), `"LEFT"` only for finding about removed line. **First line of `body` always**: `<!-- pr-review-watch: reviewed-at {headRefOid} -->` — invisible in rendered GitHub markdown, read back by Step 4 on future runs.
    - Post: `gh api repos/<owner>/<repo>/pulls/<number>/reviews --method POST --input <tmpfile>`. Never `event: "APPROVE"` or `"REQUEST_CHANGES"`, **even on ✅ Approve verdict** — runs unattended, must not approve or block merges on user's behalf. Human still clicks real Approve button after reading comments.
    - `line` outside current diff hunk → GitHub rejects that comment (422). Drop from `comments`, move text into body's bullet list, retry post once. Non-Spring generic path (Step 9, no file:line rubric) → same mechanism when findings have clear location, else falls back to bullets in body.

12. **Update state** — after handling PR (reviewed, judged trivial, all-covered, or resynced via Step 4's durable check), write current `headRefOid`, `lastCommentId`, and `flaggedCommentIds` (Step 3a) into `~/.claude/pr-review-watch/state.json`.

13. **Report** — repo-list runs (config or repo-args, arriving here via Step 0's `--once` loop tick or an explicit `--once` call): print a status summary every cycle — this is the ongoing visibility the loop exists for, not noise to minimize. Format:
    ```
    ## PR Watch — {timestamp}

    ⚠️ Build status not checked — confirm Jenkins is green for each head commit before trusting a review below.

    | Repo | Open PRs | Reviewed this cycle | Waiting (no changes) | Auto-replied | Needs human input | Errors |
    |---|---|---|---|---|---|---|
    | {owner/repo} | {n} | {n} | {n} | {n} | {n} | {n} |
    | **Total** | **{n}** | **{n}** | **{n}** | **{n}** | **{n}** | **{n}** |

    Reviewed this cycle: {for each — "owner/repo#N: {title} — {Verdict/mode or 'no new findings'}", or "none"}
    Auto-replied: {for each — "owner/repo#N (@user): {one-line paraphrase} — replied", or "none"}
    Needs human input: {for each — "owner/repo#N (@user): {one-line paraphrase} — {comment url}", or "none"}
    Drafts excluded: {n, if any}
    Own PRs excluded: {n, if any}
    Errors: {repo/PR + reason, if any}
    Next check: in {interval} — or "single run, not looping" for `--once`
    ```
    "Open PRs" = Step 2's listing count (non-draft, non-self-authored). "Reviewed this cycle" = Step 3's different/absent bucket, however it resolved (posted comment, dedup'd to nothing, or resynced via Step 4). "Waiting" = Step 3's equal/unchanged bucket. "Auto-replied" / "Needs human input" = Step 3a's two action buckets, tallied regardless of which Step 3 branch the PR took.

    Explicit PR-target runs: user asked for this one PR directly, show full result (Verdict/findings, "no changes", or "already covered by @user's comment" message) plus any Step 3a follow-up result, plus the same build-status reminder line — no table needed, this is already a direct answer to a direct ask.

13b. **Pace next check (adaptive loop only)** — skip for fixed-interval loops (`--every`/`--loop <Nm>` — `loop` skill reschedules itself) and single-shot runs. Adaptive loop ends each tick by picking own next wake time, not flat interval — call `ScheduleWakeup` with same `/pr-review-watch --once {targets + filter flags}` prompt:
    - Reviewed or replied to something this cycle → `delaySeconds` 900. Recent activity, worth checking back reasonably soon for fast-follow commits/comments.
    - Nothing changed, or no open PRs at all → `delaySeconds` 1800. Report notes watch is idle, can stop if nothing expected soon.
    `reason` names what's being waited on (e.g. "owner/repo#42 reviewed, watching for follow-up").

## Notes

- **Repo-list mode loops with adaptive pacing by default** (via Step 0) — `/pr-review-watch` alone starts an ongoing recurring check, not a single one-off. Backs off once quiet (Step 13b) — force a flat cadence with `--every <Nm>` if preferred. Use `--once` for just one cycle. Loop only starts inside a live session (same constraint as `/loop` itself) — stops if the session closes; no OS-level persistence.
- Every cycle posts a status table in-session (Step 13) — open/reviewed/waiting/error counts per repo, plus totals. Deliberately not silent — this is the visibility the loop exists for, distinct from the GitHub comments themselves.
- Requires `gh` CLI authenticated with access to target repos (`gh auth status`).
- Never review same commit twice on a PR — state file (fast path) plus GitHub-side marker (Step 4, durable fallback) together prevent it, even across lost `state.json` or a session dying mid-cycle.
- Never restate a finding a human reviewer already raised — Step 10 checks existing PR comments/reviews (excluding own account) before every post.
- Repo-list mode skips PRs authored by current `gh` user (Step 2) — own work, not for review. Explicit PR-targets bypass this, reviewed even if self-authored, since user named it directly.
- **Two scoping models.** Repo-first (default): repos.json/args list, optional `--author a,b` filter keeps only those authors' PRs — bounded to your service set. User-first (`--org gdncomm --author a,b`): `gh search prs` across whole org, `--exclude-repo` denylist subtracts noisy repos — follows people wherever they open PRs, auto-picks-up new repos. `--org` present → user-first; absent → repo-first. Both drop drafts + own PRs; explicit PR-targets exempt from both.
- **User-first needs an org scope.** `--org` bounds the search — without it `gh search prs --author x` would return that author's PRs everywhere the token sees (public repos, other orgs). Always pair `--author` with `--org` in user-first mode; `--author` alone stays repo-first.
- **Does not check Jenkins build status** — reviews whatever diff is on the PR regardless of build state. Every report (Step 13) reminds the user to confirm the build is green for the head commit before trusting the review.
- Follow-up comments checked every cycle, even PRs with no new commit (Step 3a) — plain technical questions about its own findings get an auto-reply; business or high-stakes calls get surfaced in Step 13's report instead, never posted. Never re-flags the same unanswered comment every cycle — `flaggedCommentIds` in state marks it seen after first report.
- Configured repo 404s or access denied → report, continue with rest, don't abort whole cycle.
- Posts under running user's own `gh` identity — each teammate needs own `gh auth login`, own `repos.json`.
- Full-pipeline escalation clones repos to disk under `~/.claude/pr-review-watch/checkouts/` — grows over cycles, one dir per repo that ever escalated. Delete manually to reclaim space; re-cloned on next escalation.
- Diff-only (Step 6) and generic (Step 9) never touch disk beyond `gh pr diff` output — no checkout needed.
