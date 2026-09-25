---
name: qa-check
description: Runs QA Cucumber/Selenium automation repo scenarios locally — no Jenkins, no token, no trigger. Two modes — execute suite (mvn/gradle + Cucumber runner against local or already-configured env) or static-check .feature files and step defs for undefined steps, unused step defs, drift between feature text and step implementation. Run-mode failure → spawns qa-automation to dig root cause and fix/exclude, same authority as the Jenkins path. Use when asked to check, run, or lint sanity/integration/regression scenarios locally, without touching Badak Jenkins. Never invoke for Jenkins build check — that's qa-jenkins-check.
---

# QA Check — Local Only

## Purpose

Local-only counterpart to `qa-jenkins-check`. Zero Jenkins dependency — no `JENKINS_CI_BADAK_*` vars, no token, no trigger/poll/retrigger. Runs against automation repo already checked out on disk.

Two modes:
- **Run** — execute suite (or tag-filtered slice) via repo's own Maven/Gradle + Cucumber runner, report pass/fail.
- **Lint** — static-check `.feature` files and step definitions, no execution: undefined steps (feature text, no matching step def), unused step defs (defined, never referenced by feature), drift (step text changed one place, not other).

Ambiguous request (mode unstated) → ask once, don't guess. Full integration suite when user wanted a 10-second lint = bad surprise, and vice versa.

## Step 0 — Resolve Automation Repo

Confirmed repos root: `~/Data/Automation/GDN/`. Same tokenize-and-match approach as `qa-jenkins-check` Step 1 — never job-name-to-repo-folder guess:

1. Tokenize service name (e.g. `PYEONGYANG_MEMBER_API` → `pyeongyang`, `member`, `api`).
2. `find ~/Data/Automation/GDN/*/src/test/java -type d -path "*/module/api/*" -maxdepth 10` — match directory name that, lowercased, contains most/all tokens.
3. Exactly one confident match → resolved.
4. Zero or multiple candidates → ask user which local repo path maps to this service.

Resolved → invoke `automation-repo-orientation` (reads existing `CLAUDE.md` if present, else explores and writes one). Fast structural context before Step 1/2.

## Step 1 — Confirm Scope

Ask (if not already stated):
- **Mode**: run or lint.
- **Test type**: Sanity / Integration / Regression, or specific `.feature` file / scenario / tag — confirmed folder convention `src/test/resources/features/{1_integration_test,2_sanity_test,3_regression_test}/`.

## Step 2a — Run Mode

1. Confirm build tool from repo root (`pom.xml` → Maven, `build.gradle*` → Gradle) and Cucumber runner class/tag-filter convention (grep `Jenkinsfile*`/`pom.xml`/existing runner class for `cucumber.filter.tags` or equivalent — reuse it, don't invent new invocation).
2. Confirm env config for local run — `src/test/resources/application-{ENV}.properties`. Ask user which `{ENV}` (e.g. `UATB`) if not obvious from repo default or prior context. Never assume prod-like env silently.
3. **Check TestLink integration state** (Maven — `com.gdn.qa.util:serenity-testlink-integration` plugin). Grep `pom.xml` for `<artifactId>serenity-testlink-integration</artifactId>`:
   - Active `<plugin>` block (not in `<!-- -->`, not in `<exclusion>`) → live, note it, continue.
   - Commented (repo convention: `<!-- Uncomment this to Integrate with testlink -->`) or absent → ask: run with TestLink reporting, or skip? Posts real results to TestLink — never assume silently.
   - User wants it on, currently commented → pom.xml edit, not a runtime flag (no profile/env-var alternative exists). Present diff (uncomment block), same permission gate as any source edit. Never auto-uncomment.
   - User declines, or already in wanted state → proceed to step 4.
4. Run scoped to confirmed test type/tag/file — e.g. `mvn test -Dcucumber.filter.tags="@Sanity"` (adjust to repo's actual tag/runner convention from step 1). Never run full suite when user scoped to one type/file.
5. Capture console output + Cucumber report (same report path convention as `qa-jenkins-check` — `target/cucumber-html-reports/` or similar, confirm from repo's own config).
6. Report pass/fail per scenario, total count, report path. Failure → same evidence discipline as `qa-automation` (log line + which `.feature`/step file it traces to).

## Step 2a.1 — DB Reachability Check (only if failure evidence implicates DB)

Fires only if failure evidence points at DB — connection timeout/refused in stack trace, DNS error, or assertion vs DB read (Mongo count/find, SQL query) back null/empty/stale. Passing assertions, locator errors, plain 4xx/5xx → skip, not DB-related.

1. Read `mongo.service.{name}.connection-string` (or `.hosts`+`.dbName`) / `sql.service.{name}.host-name` from same `application-{ENV}.properties` used in step 2. Never print/log/paste credential values — read programmatically, connect, nothing more.
2. Read-only reachability check only — open connection / lightweight ping (`SELECT 1`, Mongo `ping`), never data-asserting query, never write.
3. Reachable + query still null/empty → DB up, evidence points to real data-state issue (stale fixture, unpublished message) — report as such, not DB outage.
4. Unreachable (timeout, DNS fail, connection refused) → report explicitly: "DB unreachable at {host} — downstream failures may be infra, not test/app logic." Don't guess further on any failure touching this DB.
5. No route to host (network/VPN) → say so explicitly, treat unconfirmed, don't guess outcome.

## Step 2a.2 — Dig and Fix (run mode, on failure)

Local run failed → spawn `qa-automation` agent, same authority as via `qa-jenkins-check`. No Jenkins build here — no retrigger loop, no retry budget, one dig cycle per failed run.

1. Pass `qa-automation`: repo path, failed `.feature` file + scenario name, console output, Cucumber report, test type (Sanity/Integration/Regression), DB-implicated flag (Step 2a.1) if any.
2. **Reconfirm repo/`.feature` match against exact failure text — never trust Step 0's best-effort match alone.** Cucumber report (step 1) gives exact failed scenario name — search `~/Data/Automation/GDN/*/src/test/resources/features/{folder}/*.feature` for a file whose content contains that exact scenario text. Matches Step 0's repo → good, guess held up. Differs, or zero/multiple matches → stop, ask user which local repo path is correct — don't guess from job-name string similarity.
3. `qa-automation` reads actual `.feature` file, step defs, page/request objects it references — classifies root cause, proposes fix, or excludes out-of-scope scenario. Always attach raw evidence behind root cause, not just prose summary — lets user verify straight from log, no manual re-dig:
   - Config/property root cause (renamed key, mismatched topic/queue, stale env value) → property name, expected value, actual value, file:line each side.
   - API root cause → actual request JSON sent + actual response JSON/status received, with endpoint and file:line of the request-builder/step.
   - Kafka root cause → actual message payload published (or "none received" if that's the finding) + topic name + consumer group, with file:line of producer/consumer step.
   - Pull exact values from console output/Cucumber report captured in step 1 — never fabricate a plausible-looking payload.
4. In-scope mechanical fix (locator, wait, test data) → present to user, get explicit permission, apply.
5. Out-of-scope root cause (confirmed or exhausted hypothesis), not scenario-deprecated → `qa-automation` excludes scenario + commits + pushes on its own, pre-authorized, no permission step (same as Jenkins path).
6. Scenario-deprecated (business-intent call), or user declines fix → nothing changed, note in report.
7. Fix applied or scenario excluded → re-run locally (Step 2a) to confirm green. Still failing → report unresolved, don't loop further without user asking again.

## Step 2b — Lint Mode

No execution. Static cross-reference only:

1. Read all `.feature` files under confirmed test-type folder(s) — extract every step line (Given/When/Then/And/But).
2. Read step definitions under `src/test/java/.../module/api/{service}/steps/` — extract every `@Given`/`@When`/`@Then` annotation pattern.
3. Cross-reference:
   - Feature step, no matching step def pattern → **undefined step**.
   - Step def pattern, never matched by any feature step → **unused step def**.
   - Feature step text and step def pattern look drifted (param count mismatch, near-identical wording with small diff) → **possible drift**, flag for human read, don't guess intent.
4. Report flat list per finding: file:line, kind (undefined/unused/drift), text involved. No fixes applied — read-only end to end in this mode.

## Step 3 — Report

```
## QA Check (Local) — {service} ({mode})

**Repo:** {repo_path}
**Scope:** {test type / file / tag}

### Run mode
- {N} passed, {M} failed
- Report: {path}
- Root cause: {confirmed | hypothesis} — {1-2 sentence root cause}
  - Evidence: {property/expected-vs-actual, or request/response JSON, or Kafka payload+topic+consumer group} — {file:line}
- DB check: {not triggered | reachable, data-state issue | unreachable at {host} | unconfirmed, no route}
- Failures ({M}):
  - {scenario} — {file:line}
  - {scenario} — {file:line}
  - ...one line per failed scenario, even if all share root cause
- Fixes applied: {file} — {summary}, or "none"
- Scenarios excluded: {scenario} — {tag added} — {root cause/hypothesis}, or "none"
- Recommendation: {who should look next — dev team for app regression, infra for environment issue, etc.}
- Next action: {retry locally | fix pending user permission | none, resolved | none, scenario-deprecated}

### Lint mode
- Undefined steps: {count} — {file:line, text}
- Unused step defs: {count} — {file:line, pattern}
- Possible drift: {count} — {file:line, both texts}
- Next action: {fix {file} directly | none, no findings}
```

## Constraints

- Never reads, requires, references `JENKINS_CI_BADAK_*` / `JENKINS_CI_*` — no Jenkins dependency, full stop.
- Never triggers, polls, touches any Jenkins job.
- Run-mode failure → spawn `qa-automation`, same authority as Jenkins path: in-scope fix needs permission, out-of-scope exclude+commit+push pre-authorized. Lint mode stays read-only end to end, no fixes.
- No retrigger loop, no retry budget here — one dig cycle per failed local run, re-run to confirm, don't loop further without user asking again.
- Never runs broader scope than user confirmed (full suite when scoped to one file/tag).
- Never guesses local repo path from job-name string similarity — resolve via Step 0's structural match, ask if ambiguous.
- Ambiguous mode (run vs lint) or ambiguous test type/scope → ask once, don't default silently.
