---
name: snapshot-deploy-qa2
description: >-
  Build a SNAPSHOT with SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES (fast build, no
  Sonar/tests), then deploy it to qa2 and/or canary-qa2. Discovers the
  target job's actual Jenkins parameters first: if it exposes
  TRIGGER_DEPLOYMENT + CANARY, the build itself deploys (one trigger per
  host, no GitOps PR needed); otherwise falls back to jenkins-ci-job (build)
  + deploy-qa2 (GitOps PR, auto-merge, deployment build), auto-detecting the
  nonprod deployment repo against the gdncomm/iam-deployment-nonprod GitHub
  team's list. Never re-implements either skill. Use when asked "buat
  snapshot skip test terus deploy ke qa2", "snapshot build and deploy to
  qa2/canary", "fast build + deploy qa2", or via /ai-plugin:snapshot-qa2.
  Run from inside the target app repo, or give owner/repo. Never touches
  preprod or prod.
---

# Snapshot Build (skip analysis/test) → Deploy QA2

Two shapes of Jenkins job exist across IAM's repos, and this skill must not assume which one it's dealing with — **discover the job's real parameters before doing anything else** (Stage 1), then take the path that job actually supports:

- **Path A — self-deploying job.** The job itself has a `TRIGGER_DEPLOYMENT` param (`QA2` forces deploy, `NONE` skips it) and a `CANARY` param (`YES`/`NO` picks the host). One build trigger *is* the deploy — no GitOps PR, no `deploy-qa2` call.
- **Path B — build-only job.** No such params. Delegate to `jenkins-ci-job` for the build and `deploy-qa2` for the GitOps-PR-based deploy, exactly as before.

Never guess which path applies from the job's name (a `PR-<n>` job is **not** inherently parameterless — some carry the full param set, as Path A above). Always check the actual discovered parameter list.

## Announce

```
[snapshot-deploy-qa2] <repo> — stage: <discover-job|path-a-deploy|path-b-build|resolve-version|resolve-deployment-repo|deploy|done|blocked>
```

## Input

Repo (auto-detect from `git remote get-url origin` if run inside a checkout, else ask for `owner/repo`). Host(s) — qa2 only, canary-qa2 only, or both. The user's own phrasing ("qa2/canaryqa2") means **both** unless they say otherwise.

## Stage 1 — Discover the job and its parameters

Delegate to `jenkins-ci-job` (Agent tool, `jenkins-ci-job:jenkins-ci-job-runner`, per that skill's own delegation rule — never run Jenkins scripts in this conversation directly): resolve the job path for the current repo/branch, then discover its parameters (`--discover-params`, or the runner's own first-run discovery step).

- **Job has `RELEASE_TYPE` *and* `TRIGGER_DEPLOYMENT` *and* `CANARY`** → **Path A**, go to Stage 2A.
- **Job has `RELEASE_TYPE` (and usually `SKIP_ANALYSIS_AND_TEST_FOR_BUILD`) but no `TRIGGER_DEPLOYMENT`/`CANARY`** → **Path B**, go to Stage 2B.
- **Job has neither `RELEASE_TYPE` nor `SKIP_ANALYSIS_AND_TEST_FOR_BUILD`** (genuinely parameterless — confirmed by discovery, not assumed from the job name) → params would be silently dropped (`warning=ignored_params_for_parameterless_job`). **Stop before triggering anything**, tell the user this job can't take a parameterized snapshot build, and ask how to proceed. Never trigger it anyway and report it as a snapshot.

**This is a real, outward CI action — expect it to need your own approval.** Triggering a Jenkins build is exactly the kind of workload-affecting action a session's own auto-mode safety checks may hold for explicit approval (denial reason seen in practice: `Interfere With Workloads`). Denied at any trigger below → **stop, report exactly what was about to run (job path, params) and why it needs approval, and wait.** Never retry through another path (a different script, a raw API call, a browser fallback) to route around that denial.

---

## Path A — Self-deploying job

One triggered build per requested host — the build's own deployment step ships it, so nothing else in this skill runs after a green build.

### Stage 2A — Trigger (one call per host)

For each host in Input:

| Host | `RELEASE_TYPE` | `SKIP_ANALYSIS_AND_TEST_FOR_BUILD` | `TRIGGER_DEPLOYMENT` | `CANARY` |
|---|---|---|---|---|
| qa2 | `SNAPSHOT` | `YES` | `QA2` | `NO` |
| canary-qa2 | `SNAPSHOT` | `YES` | `QA2` | `YES` |

`TRIGGER_DEPLOYMENT=DEFAULT` does **not** deploy a SNAPSHOT (per the job's own param description) — always use `QA2` explicitly here, never leave it at its default. Leave any other discovered params (`AI_AGENT_RETRY_COUNT`, etc.) at default unless told otherwise.

Trigger, then monitor to a terminal result (the runner does this automatically) before moving to the next host — **sequential, not parallel**, same principle `deploy-qa2` itself uses across hosts. Two hosts requested → run this twice, once per row above.

Red on any host → report which host, build number, result, build URL, and stop; do not trigger the remaining host off a build that hasn't been confirmed working, unless the user says to proceed anyway.

### Report (Path A)

```
stage=done | blocked
repo=<owner/repo>
path=A (self-deploying job)
qa2=<build n> <SUCCESS|FAILURE> (<build_url>) | not requested
canary-qa2=<build n> <SUCCESS|FAILURE> (<build_url>) | not requested
```

---

## Path B — Build-only job (fallback)

### Stage 2B — Trigger the SNAPSHOT build

- `RELEASE_TYPE=SNAPSHOT`
- `SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES` — one-off (`--params`, no `--save-params`), so this run skips tests/analysis without changing the repo's cached default for future normal builds
- Any `TRIGGER_DEPLOYMENT`-shaped param present but without a matching `CANARY` param → set it to whatever means "don't auto-deploy" (e.g. `NONE`) — deployment for this path is `deploy-qa2`'s job, not the build's.
- Monitor to a terminal result.

Red → report the failure (build number, result, build URL) and stop. Do not fall back to a full build, do not deploy a failed snapshot. This skill has no fix-and-retry loop — that's `/sdlc-build`'s CI stage, not this one.

### Stage 3B — Resolve the built version

The snapshot build bumps the project's version (e.g. Maven `X.Y.Z-SNAPSHOT`). Get the exact string that was actually built — never guess or reuse a stale local version:

1. Ask `jenkins-ci-job` for this build's log (fetch build log operation, job + build number from Stage 2B).
2. Grep it for the version the build published — typical patterns: `Building .* X\.Y\.Z-SNAPSHOT`, `Setting version to X\.Y\.Z-SNAPSHOT`, a Maven `Building <artifact> X.Y.Z-SNAPSHOT` line, or the tag/commit the build pushed. The exact log format is per-repo; if nothing matches confidently, say so and ask the user to paste the version rather than guessing.
3. Confirm the resolved version once in the report before Stage 5B — a wrong version deploys the wrong build.

### Stage 4B — Detect the deployment repo

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

### Stage 5B — Deploy to qa2 / canary-qa2

Invoke `Skill(deploy-qa2, "<owner/repo> version <resolved version> — nonprod deployment repo is <resolved deployment_repo>, deploy to <host(s) from Input>")`. Handing over the resolved deployment repo directly satisfies `deploy-qa2`'s own Step 0 without it needing a second Jenkinsfile lookup. Let `deploy-qa2` run the rest of its flow in full: canary-layout detection, properties-change question, GitOps PR + auto-merge, deployment build — this skill does not duplicate any of that. `deploy-qa2` already refuses to default to "both" silently, so if the user only said "qa2/canaryqa2" loosely, its own Step 2 question is the real confirmation gate, not a formality to skip.

### Report (Path B)

```
stage=done | blocked
repo=<owner/repo>
path=B (build-only job → deploy-qa2)
snapshot_build=<build n> <SUCCESS|FAILURE> (<build_url>)
version=<X.Y.Z-SNAPSHOT>
deployment_repo=<name> (team-list match | jenkinsfile fallback | user-picked)
deploy=<deploy-qa2's own Return Format, relayed as-is>
```

---

## Rules

- **Discover parameters before choosing a path — never infer from the job name.** A `PR-<n>` job can be fully parameterized (including `TRIGGER_DEPLOYMENT`/`CANARY`) or have no params at all; only the discovered list says which.
- **Path A: `TRIGGER_DEPLOYMENT=QA2`, never `DEFAULT`, for a SNAPSHOT.** `DEFAULT` silently skips deploying a SNAPSHOT per the job's own param description — using it here would build successfully and deploy nothing.
- **Path A hosts are sequential, one trigger each.** `CANARY` is a single YES/NO per build; two hosts means two triggers, never parallel.
- **Path B: reuse, never rebuild.** The build is `jenkins-ci-job`'s job, the deploy is `deploy-qa2`'s job. This skill only carries the version and the resolved deployment repo between them.
- **`SKIP_ANALYSIS_AND_TEST_FOR_BUILD=YES` is a one-off override**, not a saved default — don't `--save-params` it, so the next plain build for this repo still runs full analysis/tests.
- **Never deploy a failed or unresolved-version build.** Red build → stop. Version not confidently found in the log (Path B) → ask, don't guess.
- **Never trigger a parameterized build against a job discovery shows has no matching params.** Confirm `RELEASE_TYPE`/`SKIP_ANALYSIS_AND_TEST_FOR_BUILD` actually exist on the resolved job before triggering — otherwise stop and ask, don't run a plain build and call it a snapshot.
- **A denied trigger is a stop, not an obstacle to route around.** Report what was about to run and why, then wait for the user — never retry via a different tool, script, or path.
- **Deployment repo match must be confident (Path B).** Ambiguous or no match → fall back to the Jenkinsfile lookup or ask; never deploy to a guessed repo.
- **Host selection is confirmed, not assumed** — "qa2/canaryqa2" in the request is a strong hint, not a substitute for confirming which host(s) actually got triggered/deployed.
- **Never touches preprod or prod.** Same boundary as `deploy-qa2` — use `prepare-pr-for-preprod-prod` for those.
