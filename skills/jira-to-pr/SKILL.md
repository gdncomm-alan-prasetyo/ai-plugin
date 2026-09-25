---
name: jira-to-pr
description: >-
  Take one Jira ticket all the way to a clean PR: breakdown + approved plan,
  QA test cases, code change + tests, open the PR, green CI, then review the
  PR and fix findings until none remain. Orchestrates existing agents
  (be-analyst/fe-analyst, qa-analyst, be-developer/fe-dev,
  be-code-reviewer/fe-code-reviewer) and skills (ticket-breakdown,
  testcase-from-jira, testcase-render, generate-tests, pr-message-generator,
  pr-review-watch, pr-fix-watch, jira-worklog). Use when asked "kerjakan
  IAM-1234 sampai PR", "take IAM-1234 to PR", "jira to PR", "ship this
  ticket", or via /ai-plugin:jira-pr. Run from inside the target service repo.
  Never merges.
---

# Jira → Test Cases → Change → PR

One ticket in, one PR out with no open review findings. You orchestrate — you do not plan, test-design, code, or review yourself. Every stage is an **existing** agent or skill; never re-implement what one of them already does.

The contract is `~/.claude/references/sdlc-orchestration.md` — read it first. This skill is `/sdlc-plan` + `/sdlc-build` run back to back in one session, with the approval gate between them. When either command's file (`~/.claude/commands/sdlc-plan.md`, `~/.claude/commands/sdlc-build.md`) is more specific than this one, it wins.

## Announce

```
[jira-to-pr] <KEY> — stage: <preflight|plan|testcase|build|ci|review-round-N|done|blocked>
```

Print it at every stage change.

## Runtime requirement

Run in the **main session** — you need the **Agent** tool (spawn personas) and **AskUserQuestion** (own the human gates). Entry points: `/ai-plugin:jira-pr <KEY>`, the `ai-plugin:jira-to-pr` agent as main thread (`claude --agent ai-plugin:jira-to-pr`), or a natural request like "kerjakan IAM-1234 sampai PR". Loaded inside a subagent without those tools → stop immediately and tell the caller to run `/ai-plugin:jira-pr <KEY>` from the main session. Do not do the personas' work inline.

## Input

A Jira key (`[A-Z][A-Z0-9]+-\d+`) or browse URL. None → ask. `JIRA_URL`/`JIRA_TOKEN` unset → ask the user to paste the ticket.

## Stage 0 — Preflight

1. Inside a git repo? Resolve the ticket's repo from `~/.claude/references/component-map.md`; cwd is not that repo → stop, say which repo to `cd` into.
2. `Type` from the component map picks the persona track:

   | Type | Analyst | Developer | Reviewer |
   |---|---|---|---|
   | backend | `be-analyst` | `be-developer` | `be-code-reviewer` |
   | frontend | `fe-analyst` | `fe-dev` | `fe-code-reviewer` |

3. `CLAUDE.md` lacks `<!-- repo-orientation:start -->` → run `repo-orientation` (backend) first.
4. Start `jira-worklog` (`start <KEY>`) — once per ticket. Already tracking → `status` only.
5. `gh auth status` ok. Jenkins env (`JENKINS_CI_URL`/`JENKINS_CI_USER_ID`/`JENKINS_CI_TOKEN`) missing → note it; CI stage will be reported as `skipped`, not faked.

## Stage 1 — Plan (sdlc-plan steps 2–3.5)

1. `.sdlc/plans/<KEY>.plan.md` already exists and is approved → reuse it, skip to Stage 2.
2. Spawn the **analyst**. It runs `ticket-breakdown` (Jira comment + acceptance criteria) and writes the plan ending in `## Implementation Todo List`, with design decision, PR plan, constraints, docs impact, estimate. Keep only `{plan_path, summary, proposed_decisions, pr_plan, constraints, docs_impact, estimate_hours, unresolved}` in context.
3. **Gate** (`AskUserQuestion`, one question): design decision(s) + todo list + PR plan + constraints + base branch (never default to `master`) + the new branch name (per Stage 3's format) + estimate + `unresolved[]`. Options: **Approve** / **Revise** (re-spawn analyst with feedback, max 3 rounds) / **Stop**.
4. `unresolved` must be 0 to approve.
5. On Approve only: Development Sub-task check-then-create exactly as `sdlc-plan.md` step 3.5 (never create a duplicate).

## Stage 2 — Test cases (after Approve, never before)

Spawn **`qa-analyst`**. It invokes `testcase-from-jira` → `test-cases/*.md` drafts (auto-runs `testcase-baseline` on first use) → `testcase-render` for delivery. Returns `{cases_written, delivery, gaps[], coverage_note}`.

- Test Tiger **sync** is a shared-state write: dry-run, show plan, confirm, then upload. Suite id / `TESTCASES_KEY` missing → surface as blocker for delivery; cases still land in `test-cases/*.md`. No silent render fallback.
- `gaps[]` → show to the user as findings, not blockers.
- The `test-cases/*.md` files are part of the change — they go into the same PR.

## Stage 3 — Build (sdlc-build step 1)

**Branch name — compute it yourself, pass it to the developer verbatim.** The developer's own `feature/<slug>` default does not apply here.

```
feature/{JIRA-KEY}-{Jira summary, spaces replaced by "-"}
```

From the ticket's **summary** (title) field:
1. Replace every space with `-`. Keep the original letter case.
2. Remove characters git refs reject: `~ ^ : ? * [ \` and control characters. Replace `/` and `.` with `-`.
3. Collapse repeated `-` into one, and trim `-` from both ends.

| Key | Summary | Branch |
|---|---|---|
| `IAM-1234` | `Add Role Filter on User List` | `feature/IAM-1234-Add-Role-Filter-on-User-List` |
| `IAM-88` | `Fix: token refresh / expiry bug` | `feature/IAM-88-Fix-token-refresh-expiry-bug` |

Check the name with `git check-ref-format --branch <name>` before creating it. The branch already exists locally or on `origin` → ask the user whether to reuse it or stop. Never silently add a suffix. A `pr_plan` with more than one PR → add `-part-<n>` to each branch name.

Spawn the **developer** with `plan_path`, `base_branch`, the computed `branch`, `pr_plan`, `docs_impact`, `constraints`, and the list of `test-cases/*.md` written in Stage 2. It:

- creates `branch` off `base_branch` (`git checkout -b <branch> <base_branch>`),
- executes the todo list verbatim,
- writes tests via `generate-tests` (backend) / `fe-integration-test` (frontend) — the Stage 2 cases are the behaviour those tests must assert,
- updates the docs named in `docs_impact`,
- builds the PR body with `pr-message-generator` (backend) / `fe-pr-message` (frontend); PR title starts with `<KEY>`.

**PR creation is a publish action:** pause `jira-worklog`, show the `gh pr create` command, confirm with the user, resume. On PR open → `jira-worklog log <KEY>` (confirm before posting — team-visible). Append the estimate line to `.sdlc/estimate-history.jsonl` per `sdlc-build.md`.

## Stage 4 — CI (sdlc-build steps 2–3)

Trigger the **PR job** `PR-<n>` (`trigger-jenkins-build` / `jenkins-ci-job`), wait for a terminal result.
Red → classify the log, hand to the developer to fix, push, re-trigger. **Max 3 fix attempts** → `blocked`. `secret_detection` / `license_compliance` → stop and escalate immediately. Risky fixes (logic, deps, migrations) → ask the user first.

## Stage 5 — Review the opened PR, fix until clean

Starts once CI is green. Goal: the PR's head commit has **no open review findings** — neither from the AI review nor from human reviewers. `<PR>` below = `owner/repo#<n>`.

This skill names `pr-review-watch` and `pr-fix-watch` explicitly, which is what their manual-only rule requires. The `pr-fix-watch-offer` rule would otherwise fire on `gh pr create` — this stage replaces that offer, so don't ask twice.

### 5a. AI review, posted on the PR

`Skill(pr-review-watch, "<PR> --once")`. An explicit PR target is reviewed even though you authored it. It picks `be-code-reviewer` / `spring-review-smart` for Spring repos, a generic scan otherwise, and posts the findings as inline PR comments via `gh`. It dedups against earlier reviews and human comments, so a re-run only posts what's new.

Also spawn the **reviewer** agent once (standalone) for the checks `pr-review-watch` doesn't do: PR scope vs the plan's PR plan, and `docs_impact` vs the diff. Post anything it finds as an extra PR comment.

### 5b. Fix the AI findings

`pr-fix-watch` **ignores comments from your own account**, and 5a posts under your account — so it will never pick these up. Hand the 5a findings (`file:line`, severity, text) straight to the **developer** instead:

- Fix every finding, P2 included — "clean" means nothing left open, not "no P0/P1".
- Developer disagrees with a finding → reply on that comment with the technical reason instead of changing code. Business/high-stakes call → ask the user, don't decide it.
- Local build/tests pass → commit (`<KEY> address review: …`) → push to the PR branch. Never force-push.
- Push → back to **Stage 4** (CI green again) before the next round.

### 5c. Human reviewer comments

`Skill(pr-fix-watch, "<PR> --once")`. It reads new reviewer comments (not yours), fixes actionable ones, pushes after local build/tests pass, replies with a counter-argument on disagreement, and holds business/high-stakes ones. Held items → `AskUserQuestion`: what should the reply or fix be. A push here → **Stage 4** again.

### 5d. Loop to clean

Repeat 5a → 5b → 5c until one round ends with all of:

- `pr-review-watch` reports no new findings on the current head commit,
- `pr-fix-watch` reports 0 fixed, 0 replied, 0 needs-human,
- CI green on that head commit.

**Cap: 3 rounds.** Not clean after 3 → `blocked`, list what is still open.

Clean, but a human hasn't approved yet → ask whether to keep watching: `Skill(pr-fix-watch, "<PR> --loop")` keeps fixing new reviewer comments in this session until the PR is approved or merged. Declined → report `/pr-fix-watch <PR> --loop` as the manual command for later.

Never merge, never resolve or dismiss a review thread yourself — the reviewer does that.

## Report

```
stage=review_clean | blocked
jira_key=<KEY>
plan_path=.sdlc/plans/<KEY>.plan.md
testcases=<N written> — <synced:N | rendered:path.xlsx (upload pending) | not delivered: reason>
pr_url=<url(s)>
ci=<build n SUCCESS on <sha> | skipped: no Jenkins env | blocked: reason> (attempts=<n>)
review_rounds=<n> — AI findings fixed:<n> replied:<n> | human comments fixed:<n> replied:<n> held:<n>
open_findings=<0 | list>
fix_watch=<looping on <PR> | not started: /pr-fix-watch <PR> --loop>
worklog=<logged Nh Mm | not logged>
```

Next steps are human: merge, then `/deploy-qa2`, `prepare-pr-for-preprod-prod`.

## Rules

- **Reuse, never rebuild.** Each stage maps to an existing agent/skill above. Missing one → stop and say which, don't improvise its job.
- **Branch name is fixed:** `feature/{JIRA-KEY}-{summary-with-dashes}` (Stage 3). Never let the developer choose its own.
- **Gate order is fixed:** plan approved → test cases → code. Test cases before approval waste work; code before test cases loses the behaviour it must satisfy.
- **Keep context lean.** Hold paths and summaries, not full plans, diffs, or logs.
- **Every outward write is confirmed:** Jira comments/Sub-tasks, Test Tiger sync, `gh pr create`, worklog. Pause `jira-worklog` at each human wait, resume after.
- **Every fix push re-runs CI.** A review round only counts as clean on a green head commit.
- **Review loop is capped.** 3 rounds of 5a–5c, then `blocked` — a review that won't converge needs a human.
- **Honest status.** Red CI is red, skipped is skipped, an unsynced case is unsynced.
- **Never merge, never deploy.**
