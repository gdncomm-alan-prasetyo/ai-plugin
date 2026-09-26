---
name: snapshot-deploy-qa2
description: >-
  Build a SNAPSHOT with SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES (fast build, no
  Sonar/tests), auto-detect which nonprod deployment repo it belongs to
  (matched against the gdncomm/iam-deployment-nonprod GitHub team's repo
  list), then deploy the resulting version to qa2 and/or canary-qa2. Chains
  the existing jenkins-ci-job (trigger + monitor the snapshot build) and
  deploy-qa2 (open GitOps PR, auto-merge, trigger deployment) skills — never
  re-implements either. Use when asked "buat snapshot skip test terus deploy
  ke qa2", "snapshot build and deploy to qa2/canary", "fast build + deploy
  qa2", or via /ai-plugin:snapshot-qa2. Run from inside the target app repo,
  or give owner/repo. Never touches preprod or prod.
---

# Snapshot Build (skip analysis/test) → Deploy QA2

Two existing skills, one after another: `jenkins-ci-job` builds and monitors the SNAPSHOT, `deploy-qa2` ships whatever version came out of it. This skill only sequences them, resolves *which* nonprod deployment repo the app maps to, and carries the version across — it does not trigger builds or edit deployment repos itself.

## Announce

```
[snapshot-deploy-qa2] <repo> — stage: <build|resolve-version|resolve-deployment-repo|deploy|done|blocked>
```

## Input

Repo (auto-detect from `git remote get-url origin` if run inside a checkout, else ask for `owner/repo`). Host(s) — qa2 only, canary-qa2 only, or both. The user's own phrasing ("qa2/canaryqa2") means **both** unless they say otherwise; still confirm once before deploying (Stage 3), since `deploy-qa2` never defaults to both silently.

## Stage 1 — Trigger the SNAPSHOT build

Delegate to `jenkins-ci-job` (Agent tool, `jenkins-ci-job:jenkins-ci-job-runner`, per that skill's own delegation rule — never run Jenkins scripts in this conversation directly):

- operation: **trigger build**
- repo: resolved above
- build type: `snapshot` (→ `RELEASE_TYPE=SNAPSHOT`)
- parameter override: `SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES` — one-off (`--params`, no `--save-params`), so this run skips tests/analysis without changing the repo's cached default for future normal builds
- then monitor to a terminal result (the runner does this automatically after trigger)

Red → report the failure (build number, result, build URL) and stop. Do not fall back to a full build, do not deploy a failed snapshot. This skill has no fix-and-retry loop — that's `/sdlc-build`'s CI stage, not this one.

## Stage 2 — Resolve the built version

The snapshot build bumps the project's version (e.g. Maven `X.Y.Z-SNAPSHOT`). Get the exact string that was actually built — never guess or reuse a stale local version:

1. Ask `jenkins-ci-job` for this build's log (fetch build log operation, job + build number from Stage 1).
2. Grep it for the version the build published — typical patterns: `Building .* X\.Y\.Z-SNAPSHOT`, `Setting version to X\.Y\.Z-SNAPSHOT`, a Maven `Building <artifact> X.Y.Z-SNAPSHOT` line, or the tag/commit the build pushed. The exact log format is per-repo; if nothing matches confidently, say so and ask the user to paste the version rather than guessing.
3. Confirm the resolved version once in the report before Stage 3 — a wrong version deploys the wrong build.

## Stage 2.5 — Detect the deployment repo

`deploy-qa2`'s own Step 0 resolves this by fetching the app repo's `Jenkinsfile` remotely and grepping its `deployment_repo: { nonprod: ... }` block — that still works and stays the fallback, but it's a round-trip per run. IAM's nonprod deployment repos are also all listed in one place — the GitHub team **`gdncomm/iam-deployment-nonprod`** — so try that first:

1. List the team's repos:
   ```bash
   gh api orgs/gdncomm/teams/iam-deployment-nonprod/repos --paginate --jq '.[].full_name'
   ```
   All of IAM's `nonprod-deployment-gdn-*` (and a couple `nonprod-deployment-shared-*`) repos come back in one call — this is the same list at https://github.com/orgs/gdncomm/teams/iam-deployment-nonprod/repositories.
2. Match the app repo's name against that list. The common pattern is `nonprod-deployment-gdn-<app-repo-name>` (e.g. `iam-rbac` → `nonprod-deployment-gdn-iam-rbac`), but it isn't exact for every service (e.g. `gdn-cas` → `nonprod-deployment-gdn-iam-gdn-cas`) — match by substring on the app repo's core name (strip a leading `iam-`/`gdn-` and try both forms), not a rigid template.
3. **Exactly one confident match** → use it, note it in the report as `deployment_repo=<name> (team-list match)`.
4. **Zero or more than one match** → don't guess between candidates. Fall back to `deploy-qa2`'s own Jenkinsfile-based Step 0 (or ask the user to pick from the listed candidates) — report it as `deployment_repo=<name> (jenkinsfile fallback)`.
5. This step only resolves *which repo*; it does not determine canary layout (branch vs `-next` repo vs none) — that stays `deploy-qa2`'s own Step 1.5, which needs to check branches inside the resolved repo anyway.

## Stage 3 — Deploy to qa2 / canary-qa2

Invoke `Skill(deploy-qa2, "<owner/repo> version <resolved version> — nonprod deployment repo is <resolved deployment_repo>, deploy to <host(s) from Input>")`. Handing over the resolved deployment repo directly satisfies `deploy-qa2`'s own Step 0 without it needing a second Jenkinsfile lookup. Let `deploy-qa2` run the rest of its flow in full: canary-layout detection, properties-change question, GitOps PR + auto-merge, deployment build — this skill does not duplicate any of that. `deploy-qa2` already refuses to default to "both" silently, so if the user only said "qa2/canaryqa2" loosely, its own Step 2 question is the real confirmation gate, not a formality to skip.

## Report

```
stage=done | blocked
repo=<owner/repo>
snapshot_build=<build n> <SUCCESS|FAILURE> (<build_url>)
version=<X.Y.Z-SNAPSHOT>
deployment_repo=<name> (team-list match | jenkinsfile fallback | user-picked)
deploy=<deploy-qa2's own Return Format, relayed as-is>
```

## Rules

- **Reuse, never rebuild.** Stage 1 is `jenkins-ci-job`'s job, Stage 2.5 only speeds up a lookup `deploy-qa2` already does, Stage 3 is `deploy-qa2`'s job. This skill only carries the version and the resolved deployment repo between them.
- **`SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES` is a one-off override**, not a saved default — don't `--save-params` it, so the next plain build for this repo still runs full analysis/tests.
- **Never deploy a failed or unresolved-version build.** Red build → stop. Version not confidently found in the log → ask, don't guess.
- **Deployment repo match must be confident.** Ambiguous or no match → fall back to the Jenkinsfile lookup or ask; never deploy to a guessed repo.
- **Host selection is confirmed, not assumed** — "qa2/canaryqa2" in the request is a strong hint, not a substitute for `deploy-qa2`'s own Step 2 gate.
- **Never touches preprod or prod.** Same boundary as `deploy-qa2` — use `prepare-pr-for-preprod-prod` for those.
