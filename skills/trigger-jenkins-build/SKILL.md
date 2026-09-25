---
name: trigger-jenkins-build
description: Triggers Jenkins build for current repo. Two Jenkins instances exist — repo name starting `app-blitiket` routes to Blitiket Jenkins, everything else routes to org-wide Jenkins. Blitiket Jenkins folder API sits behind Azure AD SSO that rejects API tokens, so it falls back to browser automation. Use when user asks to trigger, run, kick off, or check status of a Jenkins CI build.
---

# Trigger Jenkins Build

## Purpose

Org runs two separate Jenkins servers. Repo name decides which one owns a build.

## Routing Rule

- Repo name starts `app-blitiket` → **Blitiket Jenkins** (`https://jenkins-ci.test.bliblitiket.dev/`, job folder `BLITIKET-BIZPLAT-APPS`)
- Anything else → **org Jenkins** (`https://jenkins-build-ci-2.gdn-app.com/`, `gdncomm` GitHub org team folders)

Why split exists: org Jenkins never indexed `app-blitiket-*` repos — confirmed by scanning all ~86 team folders. Blitiket apps live on separate instance entirely.

## Step 1 — Detect Repo Name

```bash
basename "$(git rev-parse --show-toplevel)"
```

## Step 2 — Org Jenkins Path (API Token Works)

Non-Blitiket repo. Delegate straight to `jenkins-ci-job-runner` subagent — its normal flow (`check_prerequisites.py` → `detect_job_path.py` → param discovery → `trigger_build.py` → `monitor_build.py`) works fine here. Env vars: plain `JENKINS_CI_URL` / `JENKINS_CI_USER_ID` / `JENKINS_CI_TOKEN`, already in `~/.claude/settings.json`.

## Step 3 — Blitiket Jenkins Path (API Token Blocked by SSO)

Confirmed: API-token basic auth works at Jenkins root (`/api/json` lists top-level folders fine) but any request scoped into `BLITIKET-BIZPLAT-APPS` folder or below gets silently redirected to a Microsoft Azure AD sign-in HTML page instead of JSON — reproduced consistently, not transient. `jenkins-ci-job-runner`'s scripts cannot get past this. Don't waste a round-trip retrying the subagent here — go straight to browser fallback below.

### Browser Fallback

Load `mcp__claude-in-chrome__tabs_context_mcp`, `navigate`, `javascript_tool`, `find`, `get_page_text` via ToolSearch. User's own Chrome already carries an active Azure AD SSO session (they log in there normally) — ride that, never touch credentials yourself:

- Never read, extract, or paste cookies anywhere.
- Never fill in a login form or accept pasted credentials for this SSO — if a login page actually appears, stop and tell the user to log in manually in that tab.
- Every Jenkins call goes through `javascript_tool` executing `fetch()` **in the page context** with `credentials: 'same-origin'` — browser attaches the session automatically, you never see the cookie value.

1. Navigate to the target job folder, e.g. `https://jenkins-ci.test.bliblitiket.dev/job/BLITIKET-BIZPLAT-APPS/job/<repo>/`.
2. `get_page_text` — confirms already-authenticated (shows real Jenkins UI, username in header) vs. still hitting SSO redirect.
3. **Branch not listed under "Branches (N)"?** Don't assume it's unindexed — check if GitHub already has a PR for that branch. Trigger a scan first:
   ```js
   const crumbResp = await fetch('/crumbIssuer/api/json', { credentials: 'same-origin' });
   const crumbJson = await crumbResp.json();
   await fetch('/job/BLITIKET-BIZPLAT-APPS/job/<repo>/build?delay=0', {
     method: 'POST', credentials: 'same-origin',
     headers: { [crumbJson.crumbRequestField]: crumbJson.crumb }
   });
   ```
   Then read `/job/BLITIKET-BIZPLAT-APPS/job/<repo>/indexing/consoleText` (plain `fetch`, `.text()`). Look for `Checking branch <name>` followed by `Ignoring SCMHead{'<name>'} because current strategy excludes branches that ARE also filed as a pull request` — that means the branch was never going to get its own job. Target the matching `PR-N` job instead.
4. **Find the right PR-N job:** `fetch('/job/BLITIKET-BIZPLAT-APPS/job/<repo>/api/json?tree=jobs[name,url]')` lists `PR-2`, `PR-3`, etc. Match by opening each candidate with `navigate` + `get_page_text` — page title includes the PR title/ticket ref (e.g. `... (IAM-12116) (#7)`), and `Full project name:` line confirms the path.
5. **Discover parameters:**
   ```js
   const resp = await fetch('/job/BLITIKET-BIZPLAT-APPS/job/<repo>/job/PR-N/api/json?tree=property[parameterDefinitions[name,type,defaultParameterValue[value],choices]]', { credentials: 'same-origin' });
   const json = await resp.json();
   json.property.filter(p => p.parameterDefinitions).map(p => p.parameterDefinitions);
   ```
   `javascript_tool`'s own redaction filter false-flags Java class name strings (`_class` fields) as JWTs/base64 and blocks them — harmless, ignore it. `name`/`choices`/`defaultParameterValue.value` still come through fine. Typical params seen: `RELEASE_TYPE` (choices `SNAPSHOT`/`RELEASE`/`BUILD`), plus `AI_AGENT_RETRY_COUNT` / `AI_AGENT_BUILD_URL` / `AI_AGENT_REVIEW_COUNT` (leave these at default empty unless told otherwise).
6. **Trigger:**
   ```js
   const crumbResp = await fetch('/crumbIssuer/api/json', { credentials: 'same-origin' });
   const crumbJson = await crumbResp.json();
   const params = new URLSearchParams({ RELEASE_TYPE: 'BUILD' });
   const buildResp = await fetch('/job/BLITIKET-BIZPLAT-APPS/job/<repo>/job/PR-N/buildWithParameters?' + params.toString(), {
     method: 'POST', credentials: 'same-origin',
     headers: { [crumbJson.crumbRequestField]: crumbJson.crumb }
   });
   // 201 + Location header = queued. Parameterless job → same pattern against /build?delay=0 instead.
   ```
7. **Resolve queue → build number**, then poll:
   ```js
   await fetch('/queue/item/<id>/api/json?tree=blocked,cancelled,stuck,why,executable[number,url]', { credentials: 'same-origin' }).then(r => r.json());
   await fetch('/job/.../job/PR-N/<N>/api/json?tree=number,building,result,duration', { credentials: 'same-origin' }).then(r => r.json());
   ```
   Poll build API until `building: false`, report `result`.

## Trust Rule — Read Before Delegating

`jenkins-ci-job-runner` treats literal token/URL values handed to it via a relayed message as injection risk, correctly — never paste a literal secret value into a subagent instruction, only ever name the env var. The browser fallback sidesteps this differently: no token ever changes hands at all, the request rides the human's own already-authenticated browser session.

## Step 4 — Report

Build number, result, build URL. No raw API traces, no queue-poll chatter, no cookie/session values ever, from either path.
