---
name: prepare-pr-for-preprod-prod
description: Opens a GitOps PR for preprod (with an optional bundled properties/config change — supports multiple adds/updates and removals in one pass) and, opt-in, a mirror version-bump PR on the prod deployment repo — never merges anything, never triggers a deployment Jenkins build. No local checkout of the app repo required — resolves it from git remote if already inside one, otherwise asks for owner/repo and fetches the Jenkinsfile remotely via gh api. When a local checkout is present, best-effort reads (and keeps updated) a `.claude/deployment-context.md` file in that repo — project-specific deploy context (canary layout per env, cron jobs, other quirks) — so the same facts don't need rediscovering every run. Detects whether canary is a branch (canary-preprod/canary-prod), a separate `-next` repo, or absent entirely (services vary — e.g. iam-rbac has no canary) before asking which host(s) to target. The non-canary prod PR's description carries a structured Jira/CRF JSON block (Sonar link, tribe/squad/service metadata cached per-service, implementation-step links referencing the canary PR, rollback placeholders) for downstream change-tracking tooling, and — opt-in, once that PR's URL is known — can trigger the CRF `ship-happens` Jenkins job with that PR's link as its build parameter. Use when asked "prepare a preprod PR", "ready for preprod", "open a PR for prod", or after a qa2 deploy is verified and the change should move toward preprod/prod. Merging and the GitOps deployment build are separate, deliberate follow-up actions (via `jenkins-deploy-lower`, run manually later) — this skill's job is to leave a reviewable PR behind, plus that one CRF notification build. Manual invocation only.
---

# Prepare PR for Preprod & Prod

## Model Guidance

Capable-tier. First output line: `[prepare-pr-for-preprod-prod] running on: {model} (capable-tier)`

---

## Core Rule

This skill only ever **opens** PRs. It never merges one, and never triggers a Jenkins build. Preprod and prod both stay strictly PR-then-human-review — the actual merge (which is what starts a real rollout) and any build trigger are a separate, deliberate action the user takes later, typically via the `jenkins-deploy-lower` agent for preprod once the PR is reviewed and approved.

Because of that, this skill calls `jenkins-deploy-lower`'s underlying scripts directly (via `scripts/run_script.py`) for the preprod PR — never the full `jenkins-deploy-lower` agent, since that agent's own flow would go on to ask a merge question this skill has no business answering.

---

## Prerequisites

No local checkout of the target service repo is required — this skill operates entirely on the *deployment* repos (cloned fresh into a temp dir per host), not the app's dev repo. If a local checkout of the app's **dev** repo happens to be the cwd, Step 2.5 uses it best-effort to read/update `.claude/deployment-context.md` — never a hard requirement, never worth asking the user to `cd` into one. Requires the `jenkins-deploy-lower` plugin installed for the preprod PR step — its scripts live under that plugin's `skills/jenkins-deploy-lower/scripts/` directory (resolve from the installed plugin location). Step 6's CRF build trigger needs `JENKINS_CI_BADAK_URL` / `JENKINS_CI_BADAK_USER_ID` / `JENKINS_CI_BADAK_TOKEN` — a separate credential set for `jenkins-np-badak.gdn-app.com`, distinct from the deploy Jenkins' `JENKINS_CI_*` vars.

---

## Step 1 — Resolve the Version

Same as any deploy step: the version the user names explicitly, or the latest tag / current app version if unambiguous — resolve tags via `gh api repos/{owner}/{repo}/tags` or `git ls-remote --tags`, not a local `git tag` (there's no local checkout to run it against). Ask if it's not clear — never invent one.

---

## Step 2 — Auto-Discover the Deployment Repos

If the current working directory is a git repo, infer the app repo from `git remote get-url origin`. Otherwise ask which service/app repo this is for (`owner/repo`) — don't require the user to `cd` into a local clone first.

Fetch that repo's root `Jenkinsfile` **remotely** — `gh api repos/{owner}/{repo}/contents/Jenkinsfile --jq '.content' | base64 -d` — rather than assuming a local checkout exists. Grep the result for GDN's `application { deployment_repo: { prod:, nonprod: } }` block:

```groovy
application: [
    tribe: "customer-experience",
    squad: "engagement",
    service_name: "pyeongyang-common",
    dev_repo: "https://github.com/gdncomm/pyeongyang-common.git",
    deployment_repo: [
        prod: "git@github.com:gdncomm/prod-deployment-gdn-pyeongyang-common.git",
        nonprod: "git@github.com:gdncomm/nonprod-deployment-gdn-pyeongyang-common.git"
    ]
]
```

- Normalize SSH → HTTPS and drop the `.git` suffix for both values: `git@github.com:gdncomm/{x}.git` → `https://github.com/gdncomm/{x}`.
- `nonprod` is used for the preprod PR (Step 4); `prod` is only used, opt-in, in Step 5.
- **Not found** → say so, ask the user for the deployment repo URL(s) directly rather than guessing one from the app repo's name.

---

## Step 2.5 — Load & Update Local Deployment Context (best-effort)

If the cwd from Step 2 is a local checkout of the app's **dev** repo (not a deployment repo), look for `.claude/deployment-context.md` at its root. No local checkout, or cwd is some other repo → skip this step entirely, proceed to Step 3 with no context file involved. Never ask the user to check one out just for this.

**File exists** → read it before Step 3/5's own detection runs. Treat its `## Canary Layout` section as a strong prior — if it already states a layout for the env being targeted, skip the branch/repo probing in Step 3 or Step 5 for that env and use the cached value directly. Its `## Notes` section (cron jobs, shared-DB quirks, anything else project-specific) is free-form context — read it, let it inform judgment calls throughout the rest of this skill (e.g. don't flag a scheduled job's absence as a gap if Notes already explains it runs elsewhere), but never treat it as this skill's own claim without a source.

**File doesn't exist** → don't create an empty placeholder speculatively. Create it only once Step 3 (or Step 5) actually detects something worth recording — see the update rule below.

**Regenerate the derivable section, preserve the human-authored one** — same convention as `system-catalog`:

```markdown
# Deployment Context — {service_name}

<!-- Canary Layout is auto-maintained by prepare-pr-for-preprod-prod / deploy-qa2 — don't hand-edit, it gets overwritten. -->
## Canary Layout
- qa2: {branch-based | repo-based (-next) | none}
- preprod: {branch-based | repo-based (-next) | none}
- prod: {branch-based | repo-based (-next) | none}

<!-- Notes is yours — anything here is preserved as-is. -->
## Notes
- (project-specific quirks: cron jobs, shared DB, non-obvious deploy behavior, etc.)
```

**Auto-update rule** — after Step 3 and again after Step 5 (if run), compare what was just detected against `## Canary Layout`'s value for that env:
- Missing or different from what's on disk → write/overwrite only that env's line, leave every other line (including all of `## Notes`) untouched.
- Same as what's already there → no write, no diff to report.
- First-ever detection for a repo with no context file yet → create the file with the template above, `## Canary Layout` filled in for whatever envs were actually checked this run (leave others as `not yet checked` rather than guessing), `## Notes` left as the empty placeholder.

Report in this skill's own output whenever the file was created or an env's line changed — silent background writes to a file living in the user's dev repo are the kind of thing that should show up, not hide in a diff they discover later.

---

## Step 3 — Detect the Canary Layout, Then Pick Host(s)

Canary is **not implemented the same way for every service** — detect it per repo rather than assuming branch-per-canary:

1. **Branch-based canary (the common case)** — a `canary-preprod` branch exists inside the same nonprod deployment repo as `preprod`.
2. **Repo-based canary (exception)** — canary is a **separate deployment repo**. Known example: `pyeongyang-member` and `pyeongyang-member-reward` — canary lives in `{nonprod-repo}-next` (e.g. `nonprod-deployment-gdn-pyeongyang-member-next`). Inside that repo, canary is already baked in at the repo level, so the branch to use there is just `preprod` (not `canary-preprod` again).
3. **No canary at all (exception)** — some services have no canary environment. Known example: `iam-rbac`. If neither a `canary-preprod` branch nor a `{repo}-next` sibling repo exists, treat this service as single-host.

Check in this order: **Step 2.5's cached `## Canary Layout` for `preprod`, if present, first** — trust it and skip straight to asking which host(s); otherwise, look for a `canary-preprod` branch in the discovered nonprod repo, then check whether `{nonprod-repo-url}-next` exists; if neither, there's no canary. Don't guess from the service name — verify before asking, unless the cache already has the answer.

Then ask: main preprod host, canary (branch or `-next` repo, per what was detected), or both — no question at all if no canary exists. Each host chosen means its own clone, its own PR — run the whole Step 3.5+4 sequence once per host.

---

## Step 3.5 — Properties/Config Change for Preprod?

Ask explicitly, per host: **does this also need a properties/config change** in the preprod deployment repo?

- **No** → version-only PR for that host.
- **Yes** → ask for the full set of changes as a list, not one key at a time — **any mix of adds/updates and removals in the same pass**:
  - **Add or update** — one or more `key=value` pairs. Not limited to a single property; take as many as the user gives.
  - **Remove** — one or more existing keys to delete outright from the properties file, when the user says a property is no longer needed. Confirm the key actually exists in that file before removing it (don't silently no-op on a typo, and don't guess which key they meant).
  - Apply every add/update/remove in that host's local clone **before** running `prepare_deployment.py`, so the version bump and all the properties changes land in one PR.

**Which subfolder depends on the layout detected in Step 3:**

- **Branch-based canary** — each branch's `properties/` tree carries `common/`, `preprod/`, and `canary-preprod/` as siblings, but only two are ever *live* from a given clone: from `preprod`, only `common/` or `preprod/` (never `canary-preprod/` — that belongs to the other branch). From `canary-preprod`, only `common/` or `canary-preprod/`.
- **Repo-based canary** — the `-next` repo is its own independent tree; its `preprod` branch's `properties/` folder is just `common/` and `preprod/` (no `canary-preprod/` sibling to avoid).
- **No canary** — just `common/` and the single host's folder.

If both hosts need different values, that's two separate passes through Step 3.5+4 (once per host per Step 3's detection), not one PR/commit touching both host trees at once. `common/` has the widest blast radius within whichever clone you're in — don't default there for convenience.

---

## Step 4 — Open the Preprod PR (per host, never merge, never trigger)

**Known bug in `jenkins-deploy-lower`'s `env_branch_resolver.py` — never pass a `canary-*` environment to `prepare_deployment.py`.** Its `resolve_base_branch()` strips the `canary-` prefix (`environment[len("canary-"):]`) and then returns *that stripped name* as the base branch — so `--environment canary-preprod` silently opens the PR against the plain `preprod` branch, not `canary-preprod`. That's correct for repos where canary is just a values-file variant on the same branch, but wrong for GDN's branch-per-canary repos. This is the actual cause of the canary-preprod PR ending up based on the wrong branch — it's the script's resolution, not our own layout detection.

**Main host (`preprod`) — use `prepare_deployment.py` normally**, unaffected by the bug:

`prepare_deployment.py --deployment-repo-url {main repo} --environment preprod` — using any properties edit from Step 3.5 already committed in the local clone. Report exactly what it returns:

- `status=guard_failed` → stop, report the Jenkinsfile environment mismatch.
- `status=restart_flag_missing` → stop, report it — nothing was committed.
- `status=no_change` → nothing to PR; report and stop.
- `status=success` → report the PR number/URL and **stop right there**. Do not call `merge_deployment_pr.py`. Do not call `trigger_deployment.py`.

**Canary host — bypass `prepare_deployment.py`'s branch resolution entirely**, same plain-git treatment already used for repo-based canary and the prod mirror PR:
1. Clone the canary repo/branch **by its real name** — `canary-preprod` (branch-based) or `preprod` on the `-next` repo (repo-based) — never let a script resolve it.
2. Read that branch's own Jenkinsfile and confirm its `environment:` pin is `preprod` (canary and non-canary share the same environment tier, just a different host).
3. Bump the version (and apply any Step 3.5 properties edits) — reuse the plugin's own `config_editor.py` functions directly (`update_deployment_config`, `ensure_restart_on_properties_change`) via a one-off `python3 -c "..."` invocation with `sys.path` pointed at the plugin's `scripts/` dir, rather than reimplementing the YAML/properties editing by hand.
4. Commit, open the PR with `gh pr create --base canary-preprod ...` (or `--base preprod` against the `-next` repo) — **explicit `--base`, never left to a script to infer**.
5. Report the PR number/URL and **stop right there** — same as the main host, no merge, no trigger.

Do not spawn the `jenkins-deploy-lower` agent to "finish the job" for either host — merging preprod is a separate, deliberate decision for later.

Two hosts chosen → run this sequence (its own clone, its own PR) for the main host, then canary — sequential, never sharing a clone, repo, or PR between hosts.

---

## Step 4.7 — Cache Per-Service Prod PR Metadata (first run only)

The **non-canary prod PR's description** (Step 5) carries a structured JSON block for downstream Jira/CRF tooling — most of its fields are constant per service, not per release. Check for a cache file first: `~/.claude/state/prepare-pr-for-preprod-prod/{app-repo-id}.json` (same `app-repo-id` derivation `jenkins-deploy-lower` uses from the git remote).

**`Tribe Leader`, `Squad`, and `Tribe Name` are static org-wide constants, not per-service — never ask for them.** Always use `"Andri Saputra"` for Tribe Leader and `"Identity and Access Management"` for both Squad and Tribe Name. If any of these is ever wrong (org changed), that's a one-line edit to this skill, not a per-service cache entry — don't accept a shorthand like `"iam"` as a substitute.

- **Cache exists** → reuse it, don't ask again.
- **No cache** → ask the user for each of these once, then write the cache file:
  - `sonarBaseUrl` — the Sonar project link **without** the branch query param, e.g. `https://sonar25.gdn-app.com/dashboard?id=com.gdn.neo.x.loyalty:loyalty-parent`. Note this is the *base* only — the `&branch=...` part is per-release, added fresh in Step 5, never cached (a release branch name from one release would be stale on the next).
  - `devRepoName`, `devTrackerUrl` — service-specific constants used verbatim in the JSON below.

`serviceName` and `tagIdPrefix` are **not** cached here — they're asked fresh every run in Step 5, alongside the other per-release fields, even though they look like per-service constants. Don't try to grep any of these out of the Jenkinsfile — none of them reliably live there. Ask once (for the cached ones), cache, done.

---

## Step 5 — Optional: Mirror the Version Bump to Prod

Ask explicitly, opt-in — never automatic: **also open a version-bump PR on the prod deployment repo, to have ready for a later prod release?**

The prod repo is branch-per-host, but with **different branch names** than nonprod: `master` is the main/non-canary host, `canary-prod` is the canary host (not `prod`/`canary-preprod` the way nonprod names things — don't assume the naming pattern carries over). And the same layout exception from Step 3 applies here too: some services split canary into a **separate prod repo** instead of a `canary-prod` branch (mirroring their nonprod `-next` convention, e.g. a `prod-deployment-gdn-pyeongyang-member-next` sibling of `prod-deployment-gdn-pyeongyang-member`), and some have no prod canary at all. Detect the same way: **Step 2.5's cached `## Canary Layout` for `prod`, if present, first**; otherwise look for a `canary-prod` branch, then a `{prod-repo}-next` sibling repo, then conclude there's no canary if neither exists.

- **No** → skip.
- **Yes** → ask which host(s): `master`, canary (branch or `-next` repo, per what was detected), or both.

**Order matters here, and it's reversed from Step 3/4: canary first, then master.** The master (non-canary) PR's description embeds a link to the canary PR (see the JSON shape below), so the canary PR must exist first. If only `master` was chosen (no canary for this service, or canary skipped deliberately), skip straight to the master steps and leave the canary step out of `implementationSteps` entirely rather than inventing a link.

**Canary host (`canary-prod`, or the `-next` repo's `master` branch) — plain version-bump PR, same as before:**
1. Clone the prod deployment repo at the canary branch/repo. `prepare_deployment.py`'s environment guard doesn't recognize prod's branch names — do this as a plain git operation, not through the jenkins-deploy-lower scripts.
2. Bump the version to the value resolved in Step 1.
3. Commit and open a PR titled `[canary-prod] Bump {service} to v{version}` with a plain body (no JSON block — that's master-only, per Step below).
4. Record this PR's URL for use in the master PR's description.

**Master (non-canary) host — version bump PR, description is the CRF JSON block:**
1. Clone the prod deployment repo at `master` (or the `-next` repo's `master` branch, if repo-based canary). Same plain-git approach as canary.
2. Bump the version to the value resolved in Step 1.
3. Ask for these **every run** — never cached, never guessed, even the ones that look like per-service constants:
   - **Release branch name** (e.g. `release/sprint-13-2026-w1`) — used to build `sonarLink` as `{cached sonarBaseUrl}&branch={that release branch name}`.
   - **Service Tier**
   - **Implementation Date/Time** (`YYYY-MM-DD HH:MM`)
   - **Canary Implementation Date/Time** (`YYYY-MM-DD HH:MM`) — only ask this one if the service actually has a canary (per Step 3/5's detection); otherwise there's no canary implementation to schedule.
   - **Service Name** (the Jira `Service Name` custom field)
   - **`tagIdPrefix`**
4. Commit, then open the PR with `gh pr create --title "[master] Bump {service} to v{version}" --body '{pr_body}'` where `{pr_body}` is the JSON **wrapped in a fenced code block** — the literal text starts with ` ```json ` on its own line and ends with ` ``` ` on its own line, so GitHub renders it as a readable JSON block instead of a wall of unformatted text. The fenced block is part of the PR body itself, not just this document's formatting:
   ```json
   {
     "sonarLink": "{sonarBaseUrl}&branch={release branch name}",
     "jira": {
       "customFields": {
         "Service Tier": "{answer from step 3}",
         "Implementation Date/Time": "{answer from step 3}",
         "Canary Implementation Date/Time": "{answer from step 3, or omit the field if there's no canary}",
         "Canary Required": "{Yes if this service has a canary per Step 3/5 detection, else No}",
         "Squad": ["Identity and Access Management"],
         "Tribe Name": ["Identity and Access Management"],
         "Tribe Leader": ["Andri Saputra"],
         "Service Name": "{answer from step 3}"
       },
       "crf": {
         "implementationSteps": [
           { "isCanary": true, "task": "Deploy Canary app version", "link": "{canary PR URL from the step above, omit this entry entirely if there's no canary}" },
           { "task": "Deploy app version", "link": "[PR-URL]" }
         ],
         "rollback": [
           { "type": "non-canary", "url": "[ROLLBACK-PR-URL]" },
           { "type": "canary", "url": "[ROLLBACK-PR-URL]" }
         ]
       }
     },
     "devRepoName": "{cached devRepoName}",
     "devTrackerUrl": "{cached devTrackerUrl}",
     "tagIdPrefix": "{answer from step 3}"
   }
   ```
   The second `implementationSteps` entry's `link` can't be known before the PR exists — it's a placeholder (`[PR-URL]`) at creation time. `rollback` is always a placeholder too — this skill never creates rollback PRs; per the user, that gets filled in automatically by another process later. Omit the `canary` rollback entry if this service has no canary.
5. Immediately after creation, run `gh pr edit {pr_number} --body '{same fenced json block, [PR-URL] replaced with the PR's own URL}'` — keep the ` ```json `/` ``` ` fence in this edit too — so the self-reference resolves. Report the final PR URL.

Never fill `Service Tier`, `Implementation Date/Time`, or `Canary Implementation Date/Time` with a guess or a default from a prior run — always ask fresh in step 3 above; those are per-release facts only the requester knows. `Canary Required` is the one field that's derived, not asked — fill it in from what Step 3/5 actually detected. Never fill `rollback` URLs — always `[ROLLBACK-PR-URL]`, never invented and never a PR this skill creates itself.

**Never mirror properties/config changes into the prod PR** — whatever was bundled for preprod in Step 3.5 (feature flags, timeouts) stays in the lower-env repo; it's for testing there, not something to carry into prod just because a version bump is being mirrored.

---

## Step 6 — Ask to Trigger the CRF "ship-happens" Build

Only reachable once the master (non-canary) prod PR from Step 5 exists and its URL is known. Ask explicitly — never automatic: **trigger the CRF `ship-happens` build now with this PR's link?**

- **No** → skip; the user runs it manually later.
- **Yes**:
  1. **Auth**: this Jenkins instance is `jenkins-np-badak.gdn-app.com` — a different host than the deployment Jenkins (`jenkins-np-deploy.gdn-app.com`), so it uses its own env vars: `JENKINS_CI_BADAK_URL` / `JENKINS_CI_BADAK_USER_ID` / `JENKINS_CI_BADAK_TOKEN` (not the plain `JENKINS_CI_*` ones, which are scoped to the deploy Jenkins). If any of the three aren't set, say so plainly and stop rather than falling back to the deploy-Jenkins credentials or asking for the value inline.
  2. **Resolve the parameter name**: the job takes exactly one build parameter, for the non-canary PR link — but don't hardcode a guessed name. Query `GET https://jenkins-np-badak.gdn-app.com/job/NONPROD/job/IAM/job/QA2/job/IAM_CRF/job/ship-happens/api/json?tree=property[parameterDefinitions[name,type]]` to list the job's actual parameter definitions. If there's exactly one, use it. If there's more than one and it's not obvious which takes a URL, ask the user which one — then cache the resolved name in `~/.claude/state/prepare-pr-for-preprod-prod/{app-repo-id}.json` alongside the other per-service fields, since the job's parameter name won't change between runs.
  3. **Trigger with the parameter**, not the bare `/build` endpoint (that only works for parameterless builds): `POST https://jenkins-np-badak.gdn-app.com/job/NONPROD/job/IAM/job/QA2/job/IAM_CRF/job/ship-happens/buildWithParameters?{param_name}={urlencoded master PR URL}`, authenticated per step 1.
  4. Report what the trigger returned (queued item location if present, or the HTTP status) — this skill doesn't poll the build to completion, just kicks it off.

Never trigger this before the master PR's real URL is known — it's the whole point of the parameter.

---

## Return Format

```
PREPARE PR | {project} v{version}
  Preprod host: PR #{n} ({pr_url}) — not merged
  Preprod host properties change: {bundled — common/preprod | none}
  Canary-preprod host: {repeat, or "skipped" if not chosen}
  Prod mirror PR (canary-prod): {PR URL, not merged | skipped}
  Prod mirror PR (master): {PR URL, not merged | skipped} — Service Tier / Implementation Date/Time / Canary Implementation Date/Time filled from this run's answers; [ROLLBACK-PR-URL] placeholders still need filling in before this goes to CRF
  CRF ship-happens build: {triggered — queued item / status | skipped}

Next step (not done here): merge each preprod PR and trigger its build via jenkins-deploy-lower once reviewed. Fill in the master prod PR's rollback placeholders before it's used for change tracking.
```

---

## Constraints

- **Never pass a `canary-*` environment to `prepare_deployment.py`** — its `env_branch_resolver.py` strips the `canary-` prefix and resolves to the wrong (non-canary) branch. Clone the canary branch explicitly by name and drive it with plain git + the plugin's `config_editor.py` functions instead.
- **Never require a local checkout of the app repo** — resolve it from `git remote` if already inside one, otherwise ask for `owner/repo` directly; fetch the Jenkinsfile via `gh api`, not a local file read.
- **Properties changes support multiple adds/updates and removals in one pass** — don't limit the user to a single key; confirm a key actually exists before removing it.
- **Never merge any PR this skill opens** — preprod, canary-preprod, or prod. That decision belongs to a human, later, via `jenkins-deploy-lower` for preprod.
- **Never trigger a deployment Jenkins build** — this skill's output for the GitOps repos is a PR, nothing more. The one exception is Step 6's CRF `ship-happens` build, which is a change-tracking job, not a deployment — and even that only runs after an explicit yes.
- **The prod PR is opt-in and version-only** — ask before opening it, and never carry properties/config changes into it.
- **Never guess a deployment repo URL from naming convention alone** — only act on what Step 2 actually finds in the Jenkinsfile; ask if it's not there.
- **preprod and canary-preprod are separate branches** — never edit a host's properties folder from the other host's clone; each gets its own clone, its own PR.
- **prod uses different branch names than nonprod** — `master` (main) and `canary-prod` (canary), not `prod`/`canary-preprod`. Never assume the nonprod naming pattern carries over.
- **Never assume one canary layout** — detect per Step 3 (and again for prod in Step 5): branch, separate `-next` repo, or none. A convention seen on one service doesn't carry over to the next.
- **Never default a bundled preprod properties edit into `common/` for convenience** — confirm host scope first.
- **Sequential across hosts** — don't run preprod/canary-preprod in parallel. For prod specifically, canary-prod must open **before** master, since master's description embeds the canary PR's URL.
- **The CRF JSON description is master-only** — the canary-prod PR keeps a plain body; never put the JSON block there.
- **Always wrap the CRF JSON in a ` ```json ` / ` ``` ` fenced code block in the PR body** — both the initial `gh pr create` and the follow-up `gh pr edit`. A bare unfenced JSON blob is unreadable in GitHub's rendered PR view.
- **Always ask for Service Tier, Implementation Date/Time, Canary Implementation Date/Time, Service Name, and `tagIdPrefix` fresh, every run** — even the ones that look like per-service constants; never guess, never reuse a prior run's answer or the per-service cache, never leave a placeholder. `Canary Required` is the one field that's derived (from Step 3/5's own detection), not asked.
- **Never invent a `rollback` URL, and never create a rollback PR** — always `[ROLLBACK-PR-URL]`; filling that in is a separate process the user handles later, out of this skill's scope.
- **Never trigger the CRF `ship-happens` build without asking first, and never before the master PR's real URL is known** — Step 6 is opt-in every time, not cached as a yes.
- **Never guess the `ship-happens` build's parameter name** — resolve it from the job's own `api/json` parameter definitions (or ask), then cache it; don't hardcode a guessed name.
- **Per-service PR-metadata fields (sonarBaseUrl, devRepoName, devTrackerUrl) are cached, not re-asked** — Step 4.7 asks once per service and writes `~/.claude/state/prepare-pr-for-preprod-prod/{app-repo-id}.json`; reuse it on every later run for that service. The release-branch part of `sonarLink` is the one piece asked fresh every run — never cached, never guessed from the current branch.
- **`Tribe Leader` (`"Andri Saputra"`), `Squad`, and `Tribe Name` (both `"Identity and Access Management"`) are hardcoded org-wide constants** — never asked, never cached per-service, and never accept a shorthand (e.g. `"iam"`) in their place. Update the literal in this skill if the org ever changes.
- **Never invent a version** — ask if it's not clear from context.
- **`.claude/deployment-context.md` (Step 2.5) is best-effort, never a requirement** — no local dev-repo checkout means this step is skipped outright, not a reason to ask the user to `cd` into one or delay the PR flow.
- **Only `## Canary Layout` is auto-maintained** — regenerate it (per-env) whenever Step 3/5 detects something new or different; `## Notes` is human-authored and never overwritten, only read for context.
- **Report every write to `.claude/deployment-context.md`** — creation or an env-line change belongs in this skill's own output, not a silent side effect the user finds later in `git diff`.
