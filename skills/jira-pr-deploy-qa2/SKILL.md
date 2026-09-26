---
name: jira-pr-deploy-qa2
description: >-
  Take a Jira ticket to a clean, reviewed PR, then build a SNAPSHOT of that
  PR's branch with SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES and deploy it to
  qa2/canary-qa2 for pre-merge verification. Chains the existing
  ai-plugin:jira-to-pr and ai-plugin:snapshot-deploy-qa2 skills back to back —
  never re-implements either. Use when asked "kerjakan IAM-1234 sampai PR
  terus deploy ke qa2", "jira to PR and deploy qa2", "ship and verify on
  qa2", or via /ai-plugin:jira-pr-qa2. Run from inside the target service
  repo. Never merges the PR, never touches preprod or prod.
---

# Jira → PR → Snapshot Deploy QA2

Two existing skills, run back to back: `ai-plugin:jira-to-pr` gets the ticket to a clean PR, `ai-plugin:snapshot-deploy-qa2` builds and ships that PR's branch to qa2 so it can be verified **before** merge. This skill only sequences the two and carries the branch across — every stage's own rules (gates, caps, never-merge) still apply in full.

## Announce

```
[jira-pr-deploy-qa2] <KEY> — stage: <pr|resolve-branch|snapshot-deploy|done|blocked>
```

## Runtime requirement

Same as `ai-plugin:jira-to-pr`: run in the **main session** (`/ai-plugin:jira-pr-qa2 <KEY>`, or a natural request). Loaded as a subagent without the **Agent** / **AskUserQuestion** tools → stop and tell the caller to run the command from the main session.

## Input

A Jira key or browse URL (same as `ai-plugin:jira-to-pr`). Host(s) for the qa2 deploy — qa2 only, canary-qa2 only, or both; default assumption is both, confirmed at Stage 3 same as `snapshot-deploy-qa2` itself.

## Stage 1 — PR (ai-plugin:jira-to-pr, unchanged)

`Skill(ai-plugin:jira-to-pr, "<KEY>")`. Run its full flow as-is — plan gate, test cases, build, CI, review-and-fix loop. Stop condition is exactly its own: `stage=review_clean` (clean PR, no open findings) or `blocked`.

`blocked` → stop here, relay its report. Do not attempt a qa2 deploy off an unresolved or unreviewed PR.

Keep from its report: `{pr_url, ci (build/sha), plan_path}`. The PR's **branch** is not in that report's text form — resolve it explicitly in Stage 2, don't parse it out of `pr_url`.

## Stage 2 — Resolve the PR branch

```bash
gh pr view <pr_number> --repo <owner/repo> --json headRefName,headRefOid
```

This is the branch `snapshot-deploy-qa2` must build — **not** the repo's default branch. If the working tree isn't already on it (`jira-to-pr`'s developer stage normally leaves it checked out there), check it out:

```bash
git fetch origin <headRefName> && git checkout <headRefName>
```

Confirm `git rev-parse HEAD` matches `headRefOid` — the PR's current head, not a stale local copy — before triggering anything.

## Stage 3 — Snapshot build + deploy (ai-plugin:snapshot-deploy-qa2, unchanged)

`Skill(ai-plugin:snapshot-deploy-qa2, "<owner/repo> — build the current branch (<headRefName>, the open PR's head), deploy to <host(s) from Input>")`. Run its full flow as-is: snapshot build with the one-off `SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES` override, resolve the built version from the log, then `deploy-qa2`'s own canary-detection + PR + auto-merge + trigger.

**If the target service's Jenkins only builds SNAPSHOT off its default branch** (no per-branch job for feature branches — check the discovered job path against `headRefName` before triggering) → stop before Stage 3's build, tell the user this service can't snapshot an unmerged branch, and report Stage 1's clean PR as the final state instead of guessing a workaround.

Red build, unresolved version, or `deploy-qa2` blocked → same as `snapshot-deploy-qa2`'s own rules: stop, report, no forcing through.

## Report

```
stage=deployed | blocked
jira_key=<KEY>
pr_url=<url>                     # from Stage 1, still open, still unmerged
pr_branch=<headRefName>@<sha>
snapshot_build=<build n> <SUCCESS|FAILURE> (<build_url>)
version=<X.Y.Z-SNAPSHOT>
deploy=<snapshot-deploy-qa2's own deploy line, relayed as-is>
```

Next step is human: review the qa2 deploy, then merge the PR — this skill never does either.

## Rules

- **Reuse, never rebuild.** Stage 1 is entirely `ai-plugin:jira-to-pr`'s flow, Stage 3 is entirely `ai-plugin:snapshot-deploy-qa2`'s flow — this skill adds only Stage 2 (branch resolution) and the sequencing between them.
- **The PR stays open.** This skill verifies on qa2 pre-merge; it never merges, and `jira-to-pr` already never does either.
- **Deploy the PR's exact head commit**, not the default branch and not a stale local checkout — verified in Stage 2 before Stage 3 starts.
- **A `blocked` Stage 1 never reaches Stage 3.** An unreviewed or CI-red PR doesn't get deployed for "verification."
- **No per-branch snapshot job → stop, don't improvise.** Report the clean PR as the end state rather than silently building the default branch instead (that would verify the wrong code).
- **Never touches preprod or prod.**
