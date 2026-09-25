---
name: qa-jenkins-check
description: Checks a QA2 Jenkins job (Badak Jenkins, Selenium/Gherkin/Cucumber) for a named service — Sanity or Integration test type — re-triggers on non-green, and on repeated failure spawns qa-automation to dig root cause. Biased toward landing green — in-scope mechanical fix applies with permission, out-of-scope root cause (confirmed or exhausted-hypothesis) gets excluded with a tracking note and committed/pushed without asking, then retriggered. Reports result only when called — no scheduled run. Use when asked to check, verify, or fix a QA2 sanity or integration Jenkins build for a service.
---

# QA Jenkins Check (Sanity / Integration)

## Purpose

On-demand replacement for manually checking "is Jenkins green today" on QA2 Selenium/Gherkin/Cucumber test suites — Sanity or Integration. Runs on Badak Jenkins (`jenkins-np-badak.gdn-app.com`) — separate instance from org Jenkins and Blitiket Jenkins. Owns its own auth/job-path logic, no delegation to `trigger-jenkins-build`.

Report only on call. No background schedule, no proactive notification.

## Step 0 — Precondition: Badak Env Vars

This skill ALWAYS uses `JENKINS_CI_BADAK_USER_ID` / `JENKINS_CI_BADAK_TOKEN` / `JENKINS_CI_BADAK_URL`. Never `JENKINS_CI_USER_ID` / `JENKINS_CI_TOKEN` / `JENKINS_CI_URL` — those are org Jenkins, a different instance with a different ID scheme. Never silently fall back to org Jenkins vars if Badak ones are missing.

Check first:

```bash
[ -z "${JENKINS_CI_BADAK_USER_ID:-}" ] && echo "MISSING: JENKINS_CI_BADAK_USER_ID"
[ -z "${JENKINS_CI_BADAK_TOKEN:-}" ] && echo "MISSING: JENKINS_CI_BADAK_TOKEN"
```

Either missing → stop, tell user to run `bash install.sh` from the `iam-agentic-ai` repo (prompts for both, persists to shell profile) or export them manually. Don't guess a value, don't reuse `JENKINS_CI_*`, don't proceed with a partial credential.

`JENKINS_CI_BADAK_URL` optional — defaults to `https://jenkins-np-badak.gdn-app.com` if unset.

## Step 1 — Resolve & Orient Automation Repo (every call, before Jenkins)

Runs every invocation, regardless of build outcome — don't gate this behind a failure. Best-effort locate the local repo before touching Jenkins at all, so `CLAUDE.md` context exists whether or not this run ends up digging into a failure.

No failed scenario exists yet at this point, so match by real structural evidence instead — Java module/package name, not job-name-to-repo-folder guessing (e.g. never assume `PYEONGYANG_MEMBER_API` → `cucumber-py-member-api` directly):

1. Tokenize service name (e.g. `PYEONGYANG_MEMBER_API` → `pyeongyang`, `member`, `api`).
2. Search `~/Data/Automation/GDN/*/src/test/java/.../module/api/*/` (per confirmed structure) for a directory name that, lowercased, contains most/all tokens (e.g. `pyeongyangmember` matches `pyeongyang`+`member`).
   ```bash
   find ~/Data/Automation/GDN/*/src/test/java -type d -path "*/module/api/*" -maxdepth 10
   ```
3. Exactly one confident match → repo resolved (best-effort — Step 5 below reconfirms/corrects this against exact scenario text once a real failure exists to match against).
4. Zero or multiple candidates → ask user once which repo this service maps to. Don't block the rest of this run on an answer — if user says skip, proceed to Step 2 without orientation and note it in the final report.
5. Repo resolved → invoke `automation-repo-orientation` on it (reads existing `CLAUDE.md` if present, else explores and writes one).
6. Continue to Step 2 regardless of orientation outcome — this step never blocks the actual Jenkins check.

## Step 2 — Resolve Job

Service name (e.g. `PYEONGYANG_MEMBER_API`) or full Jenkins URL given, plus test type — `Sanity` (default) or `Integration`.

- Full URL → use as-is, infer test type from the URL's folder segment (`.../QA2/job/Sanity/...` vs `.../QA2/job/Integration/...`).
- Service name → build path: `{JENKINS_CI_BADAK_URL}/job/NONPROD/job/IAM/job/QA2/job/{TestType}/job/{SERVICE}_QA2_{TESTTYPE}/` where `{TestType}` is `Sanity`/`Integration` and `{TESTTYPE}` is its uppercase form.
  - Confirmed job naming, both folders: `{SERVICE}_QA2_SANITY` under `.../QA2/job/Sanity/`, `{SERVICE}_QA2_INTEGRATION` under `.../QA2/job/Integration/` (e.g. `PYEONGYANG_MEMBER_API_QA2_INTEGRATION`). Some integration jobs carry an extra suffix (`_ROBUST`, `_PARALLEL`) — if the plain `{SERVICE}_QA2_INTEGRATION` name 404s, list the folder (`{base}/job/NONPROD/job/IAM/job/QA2/job/Integration/api/json`) and match by prefix before giving up.
- Ambiguous request (service name given, no test type stated, and it's not obvious from context) → ask which one rather than defaulting silently.

Confirmed live against `PYEONGYANG_MEMBER_API_QA2_SANITY`: reads work fully anonymous on this instance (no credential validated). Authenticated action needs Basic auth with `JENKINS_CI_BADAK_USER_ID`:`JENKINS_CI_BADAK_TOKEN` — Bearer alone or mismatched ID/token 401s or redirects to `/securityRealm/commenceLogin`. WhoAmI check confirms a credential pair is real, not just riding anonymous read:

```bash
curl -s -u "${JENKINS_CI_BADAK_USER_ID}:${JENKINS_CI_BADAK_TOKEN}" "${JENKINS_CI_BADAK_URL:-https://jenkins-np-badak.gdn-app.com}/me/api/json"
```

200 + user JSON → good. 401 → wrong ID/token pair. 403 + `commenceLogin` redirect → hit SSO-gated path with no credential attached (shouldn't happen once Basic auth wired correctly).

## Step 3 — Check Last Build Status

```bash
curl -s -u "${JENKINS_CI_BADAK_USER_ID}:${JENKINS_CI_BADAK_TOKEN}" \
  "{job_url}/lastBuild/api/json?tree=number,result,building,url"
```

- `result: SUCCESS` → done. Report green, build number, build URL. Stop here.
- `result: FAILURE`/`UNSTABLE`/`ABORTED`, or no result yet → continue to Step 4.

## Step 4 — Re-trigger

Job is parameterized (confirmed: `MODE`, `TEST_SCOPE`, `NUM_OF_RERUN`, `SEND_EMAIL`, `EMAIL_RECIPIENT`, etc — defaults from job config). Plain `/build` 400s ("This page expects a form submission") on parameterized job — always use `/buildWithParameters`.

```bash
base="${JENKINS_CI_BADAK_URL:-https://jenkins-np-badak.gdn-app.com}"
crumb_json=$(curl -s -u "${JENKINS_CI_BADAK_USER_ID}:${JENKINS_CI_BADAK_TOKEN}" "${base}/crumbIssuer/api/json")
crumb=$(echo "$crumb_json" | python3 -c "import sys,json;print(json.load(sys.stdin)['crumb'])")
field=$(echo "$crumb_json" | python3 -c "import sys,json;print(json.load(sys.stdin)['crumbRequestField'])")
curl -s -X POST -u "${JENKINS_CI_BADAK_USER_ID}:${JENKINS_CI_BADAK_TOKEN}" -H "${field}: ${crumb}" \
  "{job_url}/buildWithParameters?delay=0&SEND_EMAIL=false"
```

**Always pass `SEND_EMAIL=false` on auto re-triggers.** Default job params email `EMAIL_RECIPIENT` (currently `aria.p@gdn-commerce.com;grace.tambunan@gdn-commerce.com`) on every trigger — fine for human clicking "Build Now," not for automated retry loop. Every other param stays at job default — don't override `MODE`/`TEST_SCOPE`/`NUM_OF_RERUN`/anything else.

201 + `Location: .../queue/item/{id}/` → queued. Resolve queue item → build number:

```bash
curl -s -u "${JENKINS_CI_BADAK_USER_ID}:${JENKINS_CI_BADAK_TOKEN}" "${base}/queue/item/{id}/api/json?tree=executable[number]"
```

Poll `{job_url}/{N}/api/json?tree=number,building,result` until `building: false`. These suites run long (confirmed on a Sanity job: still building past 6+ minutes) — poll on spaced interval (e.g. every 20-30s), no tight-loop.

- `SUCCESS` → report green (recovered on retrigger — likely flaky), build number, URL. Stop.
- Still failing → continue to Step 5.

## Step 5 — Dig and Fix Loop (max 2 attempts)

First re-trigger (Step 4) still unstable/failing → don't just read logs, check real automation source. Retry budget: 2 dig-and-fix cycles. Each cycle:

1. Fetch console log: `{job_url}/{N}/consoleText`
2. Fetch Cucumber report — check `{job_url}/{N}/cucumber-html-reports/` or `{job_url}/{N}/testReport/api/json`. Extract exact failed scenario name(s) + feature/controller name — ground truth for sub-step 3 below, not console log's free text.
3. **Reconfirm local automation source against exact scenario text — never trust Step 1's best-effort match alone.** Automation repos root: `~/Data/Automation/GDN/`. Confirmed structure per repo (Maven/Java + Cucumber): `src/test/resources/features/{1_integration_test,2_sanity_test,3_regression_test}/*.feature`, step defs under `src/test/java/.../module/api/{service}/steps/`.
   - Search the folder matching this run's test type — `1_integration_test` for an Integration job, `2_sanity_test` for a Sanity job — under `~/Data/Automation/GDN/*/src/test/resources/features/{folder}/*.feature`, for a file whose content contains exact failed scenario name/text pulled from cucumber report in step 2.
   - Exactly one repo matches → confirmed. Note repo path + matched `.feature` file path. Matches Step 1's repo → good, best-effort guess held up. Differs → trust this exact match, note the correction (Step 1's module-name match was a heuristic; this is ground truth).
   - Zero or multiple matches → stop, ask user which local repo path is correct. Don't guess from job-name string similarity (e.g. "PYEONGYANG_MEMBER_API" → `cucumber-py-member-api` isn't mechanical transform — confirmed here only by matching real scenario text, not name-guessing).
   - Integration scenarios may carry `@Kafka` tags and cross-service SQL/await steps (per `@Integration @TestSuiteId=...` convention) — note this in what's passed to `qa-automation`, doesn't change the classification/scope rules, just extra context for root-causing.
4. **Confirm local checkout matches what Jenkins actually built — never assume.** Fetch build's git info:
   ```bash
   curl -s -u "${JENKINS_CI_BADAK_USER_ID}:${JENKINS_CI_BADAK_TOKEN}" "{job_url}/{N}/api/json" | python3 -c "
   import sys,json
   d=json.load(sys.stdin)
   for a in d.get('actions',[]):
       if a and a.get('_class')=='hudson.plugins.git.util.BuildData':
           print(a['remoteUrls'], a['lastBuiltRevision'])"
   ```
   Multiple `BuildData` entries can appear (shared libraries, etc) — match the one whose `remoteUrls` corresponds to confirmed repo (compare against `git -C {repo_path} remote get-url origin`), not just first entry. Extract branch name (strip `refs/remotes/origin/` prefix) and commit SHA from `lastBuiltRevision`.
   - `git -C {repo_path} rev-parse --abbrev-ref HEAD` and `git -C {repo_path} rev-parse HEAD` → compare against Jenkins' branch/SHA.
   - `git -C {repo_path} status --porcelain` → check uncommitted changes, **regardless of branch/commit match**.
   - Branch/commit match AND working tree clean → confirmed, proceed confidently.
   - Branch/commit mismatch → don't auto-checkout. Per standing git safety rules: never discard uncommitted work. Report mismatch to user (local branch/commit vs Jenkins branch/commit), ask before switching — checking out over unstashed changes is user's call, not this skill's.
   - Working tree dirty (even if branch/commit match) → don't silently trust local file content as "what Jenkins ran." Note exactly which files modified — any in failing scenario's path (`.feature`, step defs, config) → flag prominently: local content may differ from what actually executed in build under investigation.
5. `automation-repo-orientation` already ran in Step 1 for this repo (unless user skipped it there, or scenario-text match in sub-step 3 above corrected to a different repo than Step 1 guessed) — only (re-)invoke it here if that's the case. Otherwise `CLAUDE.md` context is already in hand.
6. Spawn `qa-automation` agent with: job URL, build number, console log, cucumber report, confirmed repo path + matched `.feature` file, branch/commit-match status + dirty-file list from sub-step 4, attempt number, prior attempt's fix + outcome (if attempt 2). Failure evidence implicates DB (timeout/refused/DNS in trace, or assertion vs DB read returning null/empty/stale) → flag in handoff so `qa-automation` runs its read-only DB reachability check (Step 4) — never guess DB up or down.
7. `qa-automation` reads actual `.feature` file, its step definitions, and any page/request object it references — classification and proposed fix, out-of-scope findings. Always attach raw evidence behind root cause, not just prose summary — lets user verify straight from log, no manual re-dig:
   - Config/property root cause (renamed key, mismatched topic/queue, stale env value) → property name, expected value, actual value, file:line each side.
   - API root cause → actual request JSON sent + actual response JSON/status received, with endpoint and file:line of the request-builder/step.
   - Kafka root cause → actual message payload published (or "none received" if that's the finding) + topic name + consumer group, with file:line of producer/consumer step.
   - Pull exact values from console log/Cucumber report fetched in sub-steps 1-2 — never fabricate a plausible-looking payload.
8. In-scope mechanical fix proposed (locator, wait, test data) → present to user, get explicit permission, apply via `qa-automation`.
9. Out-of-scope root cause, not a scenario-deprecated call → `qa-automation` already excluded the scenario + committed + pushed on its own (pre-authorized, see its Step 5 / Constraints) — no permission step needed here.
10. Fix applied or scenario excluded → re-trigger build (Step 4 pattern, `SEND_EMAIL=false`), poll to completion.
    - `SUCCESS` → report green, note fixes applied / scenarios excluded, stop.
    - Still failing → loop to next attempt (if budget remains).
11. Scenario-deprecated (business-intent call) or user declined a proposed fix → nothing changed, retriggering won't help. Skip straight to Step 6 without burning remaining budget.

## Step 6 — Report (after 2 failed attempts or no fix possible)

```
## QA Check — {service} ({Sanity | Integration})

**Job:** {job_url}
**Final build:** #{N} — {result}
**Attempts:** {re-trigger count} re-trigger(s), {dig-and-fix count} fix cycle(s)

### Fixes Applied
- {file} — {summary}, or "none"

### Scenarios Excluded (needs follow-up)
- {scenario} — {tag added} — {root cause / hypothesis} — owner: {cross-team | dev | infra}, or "none"

### Findings (unresolved — sign-off pending)
- **{Scenario}** — {classification}: {root cause / hypothesis}
  - Evidence: {property/expected-vs-actual, or request/response JSON, or Kafka payload+topic+consumer group} — {file:line}
  - {out-of-scope reason if applicable}

### Recommendation
{who should look next — dev team for app regression, infra for environment issue, etc.}

### Next Action
{retry later | escalate to dev/infra owner named above | fix pending user permission | none, sign-off pending}
```

No raw curl/API traces, no queue-poll chatter — clean summary only.

## Constraints

- Never write to Badak Jenkins credentials/config.
- Never exceed 2 dig-and-fix cycles per invocation without user asking again.
- `qa-automation` scope stays test-automation-code only — app source changes are always a report, never an auto-fix.
- DB investigation is read-only, always — connection details come from the confirmed repo's own env config (`application-{ENV}.properties`). `qa-automation` never prints the actual credential values, and states the limitation rather than fabricating a root cause if the host isn't reachable.
- Never guess the local automation repo path from job-name similarity — confirm via matching real scenario text, or ask user if no confident match.
- Never assume local checkout matches Jenkins — confirm branch/commit against build's git info, flag any working-tree dirt, never auto-checkout over uncommitted changes without asking.
- Step 1 (repo resolve + orientation) runs every call, not just on failure — never gate `CLAUDE.md` context behind reaching the dig-and-fix loop.
- Default bias: keep Jenkins green. `qa-automation` excluding an out-of-scope scenario (with a tracking note) is pre-authorized — don't ask permission before that commit/push, only before an in-scope source-code fix or a scenario-deprecated call.
