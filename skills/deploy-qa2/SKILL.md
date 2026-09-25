---
name: deploy-qa2
description: Deploys the current version to the qa2 lower environment (main host and/or canary). No local checkout of the app repo required — resolves it from git remote if already inside one, otherwise asks for owner/repo and fetches the Jenkinsfile remotely via gh api. Detects whether canary is a branch in the same repo, a separate `-next` repo, or absent entirely (services vary — e.g. iam-rbac has no canary) before asking which host(s) to target. Always opens a GitOps PR for history, then auto-merges immediately without asking (qa2 is a fast-iteration environment) and triggers the Jenkins build. Bundles a properties/config change into the same PR when one is needed — supports multiple adds/updates and removals in one pass — asking which host-scoped subfolder it belongs in. Use when asked "deploy to qa2", "restart qa2", "bump qa2 version", "ship this to qa2". Never touches preprod or prod — see prepare-pr-for-preprod-prod for those. Manual invocation only.
---

# Deploy to QA2

## Model Guidance

Capable-tier. First output line: `[deploy-qa2] running on: {model} (capable-tier)`

---

## Core Rule

qa2 is a fast-iteration environment: this skill always opens a PR (so the change is on record) but never asks a merge question — it merges immediately and triggers the build itself. This is a deliberate divergence from `jenkins-deploy-lower`'s own agent, which always stops to ask "merge PR directly vs open in Chrome." Because that gate can't be skipped once the full agent is invoked, this skill calls `jenkins-deploy-lower`'s underlying scripts directly (via its `scripts/run_script.py` wrapper) instead of spawning the `jenkins-deploy-lower` agent.

The environment guard and restart-bump guard baked into those scripts still run in full — this skill removes the human merge question, not the safety checks.

---

## Prerequisites

No local checkout of the target service repo is required — this skill operates entirely on the *deployment* repos (cloned fresh into a temp dir per host), not the app's dev repo. Requires the `jenkins-deploy-lower` plugin to be installed — its scripts live under that plugin's `skills/jenkins-deploy-lower/scripts/` directory (resolve the actual path from the installed plugin location; don't hardcode a path from a prior session).

---

## Step 0 — Resolve the App Repo and Its Deployment Repo

If the current working directory is a git repo, infer the app repo from `git remote get-url origin`. Otherwise ask which service/app repo this is for (`owner/repo`) — don't require the user to `cd` into a local clone first.

Fetch that repo's root `Jenkinsfile` **remotely** — `gh api repos/{owner}/{repo}/contents/Jenkinsfile --jq '.content' | base64 -d` — rather than assuming a local checkout exists. Grep the result for GDN's `application { deployment_repo: { nonprod: ... } }` block (see `prepare-pr-for-preprod-prod`'s Step 2 for the exact shape). Normalize SSH → HTTPS, drop `.git`. This is the `nonprod` repo Step 1.5 onward refers to.

- **Found** → use it, and pass it explicitly to `jenkins-deploy-lower`'s scripts so they never need their own first-run question.
- **Not found** (non-standard Jenkinsfile, private repo `gh` can't read, etc.) → say so, ask the user for the deployment repo URL directly. Never guess one from the app repo's name alone.

---

## Step 1 — Resolve the Version

Determine what's being deployed: the version the user names explicitly, or the latest tag / current app version if unambiguous — resolve tags via `gh api repos/{owner}/{repo}/tags` or `git ls-remote --tags`, not a local `git tag` (no local checkout to run it against). If neither is clear, ask — don't guess a version. (No release notes are generated here; that's a separate, standalone step via `write-release-notes` if the user wants it.)

---

## Step 1.5 — Detect the Canary Layout (don't assume one convention)

Canary is **not implemented the same way for every service** — detect it per repo rather than assuming branch-per-canary:

1. **Branch-based canary (the common case)** — a `canary-qa2` branch exists inside the same nonprod deployment repo as `qa2`. Most services work this way.
2. **Repo-based canary (exception)** — canary is a **separate deployment repo**, not a branch. Known example: `pyeongyang-member` and `pyeongyang-member-reward` — their canary lives in a sibling repo named `{nonprod-repo}-next` (e.g. `nonprod-deployment-gdn-pyeongyang-member-next` is the canary counterpart of `nonprod-deployment-gdn-pyeongyang-member`). Inside that `-next` repo, canary is already "baked in" at the repo level, so the branch you use there is just `qa2` (not `canary-qa2` again) — the repo itself is the canary variant.
3. **No canary at all (exception)** — some services simply don't have a canary environment. Known example: `iam-rbac`. If neither a `canary-qa2` branch nor a `{repo}-next` sibling repo exists, treat this service as single-host and skip every canary-related question below.

Check in this order: look for a `canary-qa2` branch in the discovered nonprod repo first; if absent, check whether `{nonprod-repo-url}-next` exists as a repo; if neither exists, there's no canary for this service. Don't guess from the service name alone — verify whichever layout applies before asking Step 2.

---

## Step 2 — Which Host(s)

Ask based on what Step 1.5 detected:

- **Branch-based** → main qa2 host (branch `qa2`) or canary (branch `canary-qa2` in the same repo), or both.
- **Repo-based** → main qa2 host (`qa2` branch of the main repo) or canary (`qa2` branch of the `-next` repo), or both.
- **No canary** → just the single host, no question needed.

Don't default to "both" — the caller may only want to iterate on one. Each host chosen means its own clone, its own PR, its own merge, its own build — run the whole Step 3+4 sequence once per host, regardless of which layout is in play.

---

## Step 3 — Properties/Config Change?

`jenkins-deploy-lower`'s scripts are reactive — they only react to a `properties/` diff already staged in the working tree, they never ask if one's needed. Ask explicitly: **does this also need a properties/config change** (feature flags, timeouts, gateway routes, etc.)?

- **No** → version-only bump.
- **Yes** → ask for the full set of changes as a list, not one key at a time — **any mix of adds/updates and removals in the same pass**:
  - **Add or update** — one or more `key=value` pairs. Not limited to a single property; take as many as the user gives.
  - **Remove** — one or more existing keys to delete outright from the properties file, when the user says a property is no longer needed. Confirm the key actually exists in that file before removing it (don't silently no-op on a typo, and don't guess which key they meant).
  - Apply every add/update/remove in the deployment repo's local clone **before** running `prepare_deployment.py`, so the version bump and all the properties changes land in one PR (and the script auto-applies the `restart:` bump).

**Which subfolder depends on the layout detected in Step 1.5:**

- **Branch-based canary** — each branch's `properties/` tree carries `common/`, `qa2/`, and `canary-qa2/` as siblings, but only two are ever *live* from a given clone: from the `qa2` branch, only `properties/common/` or `properties/qa2/` (never `properties/canary-qa2/` — that belongs to the other branch's Consul sync). From the `canary-qa2` branch, only `common/` or `canary-qa2/`.
- **Repo-based canary** (e.g. `pyeongyang-member`, `pyeongyang-member-reward`) — the `-next` repo is its own independent tree, so its `qa2` branch's `properties/` folder is just `common/` and `qa2/` (there's no `canary-qa2/` sibling to avoid — the whole repo already is the canary variant).
- **No canary** — just `common/` and the single host's folder, no cross-host caution needed.

If both hosts need a change with **different values**, that's two separate passes through Step 3+4 (once per host — different branch, or different repo, per Step 1.5's detection), each editing only its own `common/`/host folder pair in its own clone — not one PR/commit touching both host trees at once. `common/` has the widest blast radius within whichever clone you're in — don't default there for convenience.

---

## Step 4 — Prepare, Merge, Trigger (per host, sequentially)

**Known bug in `jenkins-deploy-lower`'s `env_branch_resolver.py` — never pass a `canary-*` environment to `prepare_deployment.py`.** Its `resolve_base_branch()` strips the `canary-` prefix before resolving the base branch (`environment[len("canary-"):]`) and then *returns that stripped name as the base branch itself* — so requesting `--environment canary-qa2` silently opens/merges the PR against the plain `qa2` branch, not `canary-qa2`. That's correct behavior for repos where canary is just a values-file variant on the same branch, but **wrong** for GDN's branch-per-canary repos, where `canary-qa2` is a genuinely separate branch. Trusting it here is exactly the "kok suka salah bikin branch canary-preprod" bug — it's not our skill misdetecting the layout, it's this script resolving to the wrong branch once we hand it a canary environment name.

**Main host (`qa2`) — use `prepare_deployment.py` normally**, this path is unaffected by the bug:
1. `prepare_deployment.py --deployment-repo-url {main repo} --environment qa2` with the resolved version and deployment type. Any properties edit from Step 3 should already be committed in the local clone before this runs.
   - `status=guard_failed` → **stop**, report the Jenkinsfile environment mismatch, do not proceed.
   - `status=restart_flag_missing` → **stop**, report it — a properties change with no `values.yaml` to carry the restart bump is a silent no-op if forced through.
   - `status=no_change` → nothing to merge or build; report and stop.
   - `status=success` → continue immediately, **without** asking a merge question.
2. `merge_deployment_pr.py --pr-number {pr_number} --deployment-repo-url {main repo}` — merge right away.
3. `trigger_deployment.py --environment qa2` with the resolved version — trigger the build immediately after a successful merge.

**Canary host — bypass `prepare_deployment.py`'s branch resolution entirely**, same plain-git treatment already used for repo-based canary and the prod mirror PR:
1. Clone the canary repo/branch **by its real name** — `canary-qa2` (branch-based) or `qa2` on the `-next` repo (repo-based) — never let a script resolve it.
2. Read that branch's own Jenkinsfile and confirm its `environment:` pin is `qa2` (canary and non-canary share the same environment tier, just a different host) before proceeding — same guard `prepare_deployment.py` would have run, just done directly against the branch we actually cloned.
3. Bump the version (and apply any Step 3 properties edits) — reuse the plugin's own `config_editor.py` functions directly (`update_deployment_config`, `ensure_restart_on_properties_change`) via a one-off `python3 -c "..."` invocation with `sys.path` pointed at the plugin's `scripts/` dir, rather than reimplementing the YAML/properties editing logic by hand.
4. Commit, open the PR with `gh pr create --base canary-qa2 ...` (or `--base qa2` against the `-next` repo) — **explicit `--base`, never left to a script to infer**.
5. Merge it directly (`gh pr merge`), then trigger the build via `trigger_deployment.py --environment canary-qa2` (branch-based) or the `-next` repo's own `qa2` build (repo-based) — `trigger_deployment.py` only resolves a Jenkins **job path**, not a git branch, so it isn't affected by this bug.

Two hosts chosen → run this entire sequence (its own clone, PR, merge, build) for the main host, then canary (or the order the user asked for) — sequential, not parallel, and never sharing a clone, repo, or PR between hosts.

---

## Return Format

```
DEPLOY QA2 | {project} v{version}
  Canary layout: {branch-based | repo-based (-next) | none}
  Host: qa2 — PR #{n} merged, build {build_number} ({build_url})
  Host: canary — {repeat, or "skipped" if not chosen/not applicable}
  Properties change: {bundled — common/{host}: N added/updated, M removed | none}
```

---

## Constraints

- **Never pass a `canary-*` environment to `prepare_deployment.py`** — its `env_branch_resolver.py` strips the `canary-` prefix and resolves to the wrong (non-canary) branch. Clone the canary branch explicitly by name and drive it with plain git + the plugin's `config_editor.py` functions instead.
- **Never require a local checkout of the app repo** — resolve it from `git remote` if already inside one, otherwise ask for `owner/repo` directly; fetch the Jenkinsfile via `gh api`, not a local file read.
- **Never ask the merge question for qa2** — that's the entire point of this skill existing separately from `jenkins-deploy-lower`'s agent. Merge and trigger happen automatically after a successful `prepare_deployment.py`.
- **Never skip the environment guard or restart-bump guard** — those come from the scripts themselves and stay in full effect; only the human merge confirmation is removed.
- **Never assume one canary layout** — detect per Step 1.5 (branch, separate `-next` repo, or none) before asking or acting; don't carry one service's convention over to another.
- **Never touch preprod or prod** — this skill's scope ends at qa2 and its canary counterpart. Use `prepare-pr-for-preprod-prod` for those.
- **Never default a properties edit into `common/` for convenience** — confirm host scope first.
- **Properties changes support multiple adds/updates and removals in one pass** — don't limit the user to a single key; confirm a key actually exists before removing it.
- **Sequential across hosts** — don't run main and canary in parallel, regardless of layout.
- **Never invent a version** — ask if it's not clear from context.
