---
name: run-ui-jenkins-get-sonar-report
description: Triggers Jenkins build for current UI repo using Jenkins URL found in root README.md or documentation/README.md, waits for completion, then pulls Sonar report using Sonar URL from same README. Use when user asks to "run jenkins and get sonar report", "check sonar after jenkins build", "run ui jenkins get sonar report", or wants build + coverage/quality-gate status in one go for a frontend repo.
---

# Run UI Jenkins, Get Sonar Report

## Purpose

UI repos (Vue/React) commit Jenkins and Sonar URLs straight into README — no folder-detection guesswork like `trigger-jenkins-build`. Reads both URLs from README, runs build, reports Sonar quality gate + coverage once analysis lands.

## Step 0 — Confirm UI Repo

Glob `package.json` at repo root. Not found → tell user skill targets frontend repos, stop.

## Step 1 — Find Jenkins + Sonar URLs

Check root `README.md` first, then `documentation/README.md`. Look for `CI / Code Quality` section (or similar) with lines like:

```
Jenkins :
https://jenkins-build-ci-2.gdn-app.com/job/GitHub/job/gdncomm/job/GDN/job/IAM/job/<repo>/

Sonar :
https://sonar25.gdn-app.com/dashboard?id=com.gdn.<repo>%3A<repo>&codeScope=overall
```

Grep pattern: `jenkins-build-ci|jenkins-ci\.` for Jenkins URL, `sonar[0-9]*\.gdn-app\.com` for Sonar URL.

Neither README has these lines → ask user to paste Jenkins job URL and Sonar dashboard URL directly.

## Step 2 — Parse Sonar URL Now (Need Before + After Build)

Sonar dashboard URL query string carries project key: `?id=<PROJECT_KEY>` — URL-decode it (`%3A` → `:`). Current git branch (`git branch --show-current`) is Sonar `branch` param unless repo on `master`/`main` — treated as main branch, no `branch` param.

Host from URL (e.g. `sonar25.gdn-app.com`) is Sonar server — no need to ask for `SONARQUBE_URL` separately, already in hand.

## Step 3 — Trigger Jenkins Build

No external skill/subagent dependency — call Jenkins REST API directly with `curl`. Job path already known from Step 1 URL, no folder-detection needed.

Needs `JENKINS_CI_USER_ID` and `JENKINS_CI_TOKEN` env vars (Jenkins API user + token). `JENKINS_CI_TOKEN` missing → tell user `export JENKINS_CI_TOKEN=...`, stop. `JENKINS_CI_USER_ID` = UUID from Jenkins profile page URL (`<jenkins-host>/user/<UUID>/`), not login name. Missing → ask user to open profile page, paste UUID from URL (`AskUserQuestion`), suggest `export JENKINS_CI_USER_ID=...` for next time — fresh value works inline, no pre-set required.

1. Branch job URL = `<JENKINS_URL_FROM_README>job/<url-encoded-branch>/` (current branch via `git branch --show-current`). Confirm exists:
   ```bash
   curl -s -o /dev/null -w '%{http_code}' -u $JENKINS_CI_USER_ID:$JENKINS_CI_TOKEN "<branch_job_url>api/json"
   ```
   `404` → branch not indexed by multibranch pipeline yet (check open PR — Jenkins may have filed under `PR-N`; `gh pr list` + retry against `<JENKINS_URL_FROM_README>job/PR-<N>/`). Still nothing → tell user to trigger pipeline scan in Jenkins first, stop.

2. Get CSRF crumb (Jenkins host = scheme+host portion of `JENKINS_URL_FROM_README`, before `/job/`):
   ```bash
   curl -s -u $JENKINS_CI_USER_ID:$JENKINS_CI_TOKEN "<jenkins-host>/crumbIssuer/api/json"
   ```

3. Trigger build:
   ```bash
   curl -s -i -u $JENKINS_CI_USER_ID:$JENKINS_CI_TOKEN -H "<crumbRequestField>: <crumb>" -X POST "<branch_job_url>build?delay=0"
   ```
   `201` + `Location` header = queued (`Location` = queue item URL).

4. Resolve queue → build number, poll build status:
   ```bash
   curl -s -u $JENKINS_CI_USER_ID:$JENKINS_CI_TOKEN "<queue_location>api/json?tree=executable[number,url]"
   curl -s -u $JENKINS_CI_USER_ID:$JENKINS_CI_TOKEN "<branch_job_url><N>/api/json?tree=number,building,result,duration"
   ```
   Poll second call (short backoff loop, or Bash `run_in_background: true` + `Monitor`) until `building: false`.

Build `result != SUCCESS` → report failure immediately (build URL + result), stop. No auto-retry, no auto-debug loop. Don't chase Sonar report for build that never ran Sonar stage successfully. Point user at `jenkins-ci-log-parser` skill for failure triage if wanted.

User explicitly asks "run until green" → loop: parse failure via `jenkins-ci-log-parser`, debug, retrigger, repeat until `SUCCESS` or user says stop. Debugging code behavior → read `documentation/` folder first, not raw source guesswork. Fall back to source only if docs missing/silent.

## Step 4 — Confirm Sonar Analysis Landed

Jenkins pipeline runs Sonar scan as stage — analysis lands on server shortly after build finishes, not instantly. Needs `SONARQUBE_TOKEN` env var (Sonar user token, `Bash` header `-u $SONARQUBE_TOKEN:`). Missing → tell user to generate one at `https://<sonar-host>/account/security`, `export SONARQUBE_TOKEN=...`, stop.

Poll (few retries, short backoff) until analysis timestamp newer than build start time:

```bash
curl -s -u $SONARQUBE_TOKEN: "https://<sonar-host>/api/project_analyses/search?project=<PROJECT_KEY>&branch=<BRANCH>&ps=1"
```

No fresh analysis after reasonable wait → report build succeeded but Sonar hasn't picked up yet, give user Sonar URL to check later, stop.

## Step 5 — Pull Report

Quality gate (conditions here are per-metric pass/fail, mostly scoped to new code):
```bash
curl -s -u $SONARQUBE_TOKEN: "https://<sonar-host>/api/qualitygates/project_status?projectKey=<PROJECT_KEY>&branch=<BRANCH>"
```

Metrics — `coverage` = overall, `new_coverage` = new code only:
```bash
curl -s -u $SONARQUBE_TOKEN: "https://<sonar-host>/api/measures/component?component=<PROJECT_KEY>&branch=<BRANCH>&metricKeys=coverage,new_coverage,bugs,vulnerabilities,code_smells,duplicated_lines_density,uncovered_lines"
```

`new_coverage` value nested under `periods[0].value`, not top-level `value` — read from there. Missing entirely → no new code in analysis (nothing changed since leak period), state that instead of number.

## Step 6 — Report

Single summary, no raw JSON dumps:

- Jenkins: build number, result, duration, build URL
- Sonar overall: coverage %
- Sonar new code: coverage %, pass/fail (cross-check against `project_status` condition where `metricKey` is `new_coverage` — its `status` field is authoritative PASSED/ERROR verdict, don't infer from raw % vs guessed threshold)
- Sonar quality gate: overall status (PASSED/FAILED/WARN), bugs, vulnerabilities, code smells, duplication %, dashboard URL

Quality gate FAILED → list every failed condition from `project_status` (metric name, actual value, comparator, error threshold), not just verdict. Always call out new-code-coverage condition explicitly (pass or fail), even when overall gate passes.
