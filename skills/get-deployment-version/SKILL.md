---
name: get-deployment-version
description: Compare application versions between dev and prod environments by reading deployment/values.yaml from configured repositories. Shows which applications need deployment and identifies version mismatches. Canary layout is per-service in the repos[] list in run.sh — branch-based (canary-qa2/canary-preprod/canary-prod, the default), repo-based (a separate "-next" deployment repo, e.g. pyeongyang-member/pyeongyang-member-reward), or none at all (e.g. IAM RBAC, marked NONE — reported as "No Canary" rather than a false Fetch Error). Use when checking deployment status, comparing versions across environments, or planning deployment activities.
---

# Get Deployment Version

## Args
- (none) → normal pipeline only
- `normal` → normal pipeline only
- `canary` → canary pipeline only
- `both` → normal + canary pipelines

## Steps

### 1. Read config
The tracked service list lives in the `repos[]` array inside `run.sh` itself (not `config.yml`, which is unused boilerplate for a different, legacy script). Each entry is `"Display Name|nonprod-repo|prod-repo|canary-nonprod-repo|canary-prod-repo"` — the last two fields are optional and encode the canary layout for that service: empty = branch-based (default), `NONE` = no canary environment exists, or a repo name = repo-based canary (a separate deployment repo, e.g. a `-next` sibling). Adding a new service to track means adding an entry here with the right layout, not guessing one convention for every service.

### 2. Run the pre-built script

Execute `run.sh` from the skill base directory, passing the mode as the first argument:

```bash
bash "{skill_base_dir}/run.sh" [normal|canary|both]
```

The script handles everything: parallel fetching, status computation, sorting, padded table rendering, summary, action items, and Jira fix-version links.

**What the script produces:**
- Padded, aligned markdown tables (one per pipeline based on mode)
- Rows sorted: Ready for QA → Ready for Prod → All Sync → Prod Newer → Fetch Error
- Summary table (single column for normal/canary, two columns for both)
- Action Items section
- Jira Fix Version Links section — clickable links for every `Ready for QA` and `Ready for Prod` service:
  - `Ready for QA`: uses DEV version with build suffix stripped (e.g. `1.50.0-4` → `1.50.0`)
  - `Ready for Prod`: uses QA version with build suffix stripped

### 3. Display output
Print the bash output directly to the user.

### 4. Export to file
Write the same output to a `.md` file in the current working directory named `compare-version-YYYYMMDD-HHmmss.md`. Tell the user the filename.
