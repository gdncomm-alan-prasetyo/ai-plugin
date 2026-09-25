---
name: testcase-from-jira
description: >-
  Generate or revise QA test cases from a Jira ticket during grooming. Use when
  asked to create test cases for a ticket, "buat test case", "generate test case
  for IAM-1234", or given a Jira browse URL. Classifies each acceptance
  criterion as new coverage or a change to an existing case, and never rewrites
  an existing case without approval.
---

# Test Cases From Jira

## Announce Model

Print before any other output:
```
[testcase-from-jira] Phase: test case generation
```

Per-ticket. Reads ticket, diffs against `test-cases/*.md`, writes drafts.

Run from inside target project repo, not this skills repo.

## Field rules live in a reference file

Storage format, frontmatter fields, enums, coverage checklist: `{skill-dir}/../testcase-render/references/test-case-rules.md`.

Read that file **once, after plan approval** — before writing any case file. Classification steps below need only the existing case titles and summaries.

If that file is missing, `render_test_cases.py validate()` is the schema authority — its checks define required frontmatter, section names, and enums. Do not guess; run validate to confirm.

## Agent behavior

- **Always plan before writing.** Never plan and write files in same response.
- **Approval is explicit.** "yes", "go ahead", "approve", "looks good", "do it". Silence or a follow-up question is NOT approval.
- **Additive by default.** Most tickets add behavior. Modifying an existing case is the exception and needs its own confirmation.
- **Never touch an UNTOUCHED case.** Do not reword, reformat, re-order, or re-tag a case the ticket does not affect. Hand-written cases are user work.
- **Never rename an uploaded case.** Upload target keys on the `test_case` name and creates new rows. A rename uploads as a duplicate. (Deleting one is fine via `REMOVED`/`retire` — that is deletion, not a rename.)
- **Never invent.** Endpoints, fields, roles, error codes not in the ticket → state the gap.
- **Delivery is `--jira`-scoped only.** Step 7 handles this ticket's cases, never the whole draft set. Applies to both sync and render.
- **Sync writes to a shared system.** Dry-run, show the plan, get a yes. Render path never `mark-uploaded` — that upload is manual.

---

## Step 0 — Resolve ticket and check baseline

Accept a key (`IAM-12080`) or browse URL. Extract key from URL.

Fetch via jira-issues CLI. Discover path — install path is version-pinned and changes on update:

```bash
JIRA_CLI=$(find ~/.claude/plugins/cache -path '*/jira-issues/*/scripts/jira_cli.py' 2>/dev/null | sort -V | tail -1)
python3 "$JIRA_CLI" get <ISSUE-KEY>
```

`$JIRA_CLI` empty, or `JIRA_URL`/`JIRA_TOKEN` unset → say so plainly, ask user to paste ticket description and acceptance criteria. Do not block.

**Check whether the description is groomed.**

After tech discussion the dev rewrites the description per `{skill-dir}/../ticket-breakdown/references/jira-description-format.md`: Summary / Decisions / Acceptance Criteria (GIVEN-WHEN-THEN) / Out of Scope / Technical Notes.

| Description state | Do |
|---|---|
| Has `Acceptance Criteria` section | Groomed. Use it. `Decisions` is authoritative over anything older — decisions are newer. |
| No `Acceptance Criteria` section | Not groomed. Warn: "description has no acceptance criteria; cases will be thin and gaps many." Ask whether to proceed or run `ticket-breakdown` first. |
| Has `Out of Scope` | Generate nothing for those items. |

Read `{skill-dir}/../ticket-breakdown/references/jira-description-format.md` for the AC → test case mapping. GIVEN becomes Preconditions, WHEN becomes Step Action, THEN becomes Expected Result. One case per AC minimum, plus negative, boundary, and permission derivations.

AC present but THEN vague ("returns an error") → generate the case, flag the missing status or error code as a gap. Never guess a code.

Cite the AC id in each case's summary so QA can trace a case to the criterion that produced it.

Check baseline:

```bash
ls test-cases/*.md 2>/dev/null | wc -l
```

Count 0 → **auto-run `testcase-baseline` first.** Do not stop, do not ask whether to baseline. Invoke it, let it seed `test-cases/`, then continue with this ticket.

> **No baseline yet — seeding first.** `test-cases/` is empty, so I am running `testcase-baseline` to derive cases from integration tests and docs before handling {KEY}.

`testcase-baseline` keeps its own plan-and-approval gate and its own per-module scope — that safety does not move here. Scope it to the module the ticket touches (from the ticket's Technical Notes paths); ask only if the module is unclear. When baseline finishes, re-read `test-cases/` and proceed to Step 1.

Baseline itself finds nothing to seed (no integration tests in scope) → it reports all-gaps and writes nothing. Then this skill proceeds ticket-only. Say so; do not loop.

## Step 1 — Read existing cases and the coverage map

Read frontmatter + `## Summary` of every `test-cases/*.md`. Do not read full bodies — titles and summaries are enough to classify.

**Read `.testcase-coverage.md` if it exists** (written by `testcase-baseline`). It maps endpoint → tested scenarios → exact codes → verdict. Use it to classify a ticket's ACs against existing coverage **without re-scanning the test suite** — the `be-review-context` cache pattern. Re-derive from source only when the file is absent or the ticket touches an endpoint not in it.

Build the map:

| File | Title | Status | Covers |
|---|---|---|---|
| IAM-11204-login-success.md | IAM-11204 - Login with valid credentials | uploaded | POST /v1/auth/login happy path |
| IAM-11204-login-locked.md | IAM-11204 - Login on locked account | uploaded | POST /v1/auth/login → 423 |

## Step 2 — Classify each acceptance criterion

Three verdicts. Binary generate-or-update loses the distinction that matters.

| Verdict | Trigger | Action |
|---|---|---|
| `NEW` | Ticket covers behavior no case covers | Write new draft |
| `AFFECTED` | Ticket **changes** behavior an existing case asserts | Propose supersede, show diff, confirm |
| `REMOVED` | Ticket **deletes** behavior an existing case asserts (endpoint dropped, feature removed, listed in Out of Scope as removed) | Propose retire, confirm, then `retire` the case |
| `UNTOUCHED` | Existing case unaffected | Do nothing. Do not read, rewrite, or reformat. |

`AFFECTED` is rare. An AC that adds a field to a response is usually `NEW` (new assertion), not `AFFECTED` (old assertion now wrong). Only classify `AFFECTED` when the existing case would now **fail** against the new behavior.

`REMOVED` is rarer still, and destructive — it deletes a case file. Only classify it when the ticket genuinely removes the behavior, not when it merely changes it (that is `AFFECTED`: supersede, keep coverage). Never `REMOVED` on a hunch.

## Step 3 — Output plan

```
Ticket: IAM-12080 — Refresh token rotation
Existing cases: 14    New: 3    Affected: 1    Removed: 1    Untouched: 12

  NEW (will write as draft):
    + IAM-12080 - Refresh with valid token rotates refresh_token   [NEW_FEATURE/P0]
    + IAM-12080 - Refresh with expired token returns 401           [NEW_FEATURE/P0]
    + IAM-12080 - Reused refresh token revokes session family      [NEW_FEATURE/P1]

  AFFECTED (needs your approval — see diff below):
    ~ IAM-11204-refresh-success.md   status: uploaded
        old Expected: "Same refresh_token returned"
        new Expected: "New refresh_token returned; old one invalidated"
        → supersede with IAM-12080-refresh-rotates.md
        → old row must be deleted manually in test management system

  REMOVED (needs your approval — deletes the file):
    x IAM-10001-legacy-sso-login.md   status: uploaded
        ticket removes the legacy SSO endpoint (Out of Scope: "SAML login deleted")
        → retire: deletes local file, its target row must be deleted by hand

  UNTOUCHED: 12 cases, not read, not modified

  Grounded by description — AC-1..AC-3, decisions D1/D2 applied:
    AC-1 → case 1     AC-2 → case 2 (D2: error code AUTH_004)
    AC-3 → case 3 (D1: revokes whole family)

  Gaps (AC present but not testable as written):
    ! AC-4 THEN says "returns an error" — no status or error code given
```

Cite the AC id, and the decision where one applies. Reviewer traces a case back to the criterion and the meeting that produced it.

## Step 4 — Confirm AFFECTED and REMOVED separately

### AFFECTED

Never bundle a supersede into blanket plan approval. Ask per affected case:

> `IAM-11204-refresh-success.md` is uploaded. Superseding means:
>   1. new case uploads as a new row
>   2. old row stays live until you delete it manually
>
> Supersede it, or leave it and add the new case alongside?

Declined → drop to `NEW` only, leave the old case alone.

### REMOVED

Never bundle a retire into blanket approval. Retire **deletes the case file**; if the case was uploaded, its target row must be deleted by hand.

> `IAM-11204-refresh-legacy.md` covers behaviour this ticket removes.
> Retiring it deletes the local file, and — since it is uploaded — you must delete its row in the test management system.
>
> Retire it?

Confirmed → run:

```bash
python3 {skill-dir}/../testcase-render/scripts/render_test_cases.py \
  retire --input test-cases/ --case <old-filename>
```

The script prints the target row to delete, then removes the file. Declined → leave the case alone.

## Step 5 — Write files

Read `{skill-dir}/../testcase-render/references/test-case-rules.md`, then write.

- `NEW` → new file, `status: draft`, `supersedes: null`
- `AFFECTED` (approved) → new file, `status: draft`, `supersedes: <old-filename>`. Leave old file untouched; `testcase-render mark-uploaded` flips it to `retired`.

## Step 6 — Verify

```bash
python3 {skill-dir}/../testcase-render/scripts/render_test_cases.py validate --input test-cases/
```

Fails → show problems, fix the `.md` files, re-run. Do not proceed to render over a validation failure.

## Step 7 — Deliver this ticket's cases

Always **scoped to this ticket only** (`--jira <KEY>`), so a teammate's half-finished drafts on the shared branch are never swept in.

Two paths. Probe once, pick one:

```bash
python3 {skill-dir}/../testcase-render/scripts/test_tiger_client.py projects --search iam
```

| Result | Path |
|---|---|
| Works, and suite id known | **Sync** → 7a |
| `key_missing=true`, or no suite id | **Stop — ask user to fix** → 7c. No auto-render. |

Missing prerequisite blocks *delivery*, not case generation — cases still land in `test-cases/*.md` as drafts. `key_missing=true` → tell user to generate a key and save it themselves (`test_tiger_client.py setup --key <key>`); never handle the key. No suite id → discover + ask user to record it (7c). Render (7b) runs only when the user explicitly wants a sheet — never as a silent fallback.

### Step 7a — Sync to Test Tiger

Suite id from `~/.claude/references/component-map.md` `Test Tiger suite` column. Missing → discover with `test_tiger_client.py suites <project-id>`, ask user to confirm. Never guess a number — a wrong suite files cases under another squad.

Dry-run, show titles, get a yes, then sync:

```bash
python3 {skill-dir}/../testcase-render/scripts/sync_test_tiger.py \
  --input test-cases/ --suite-id <id> --jira <KEY> --dry-run

python3 {skill-dir}/../testcase-render/scripts/sync_test_tiger.py \
  --input test-cases/ --suite-id <id> --jira <KEY>
```

Confirmed cases go `uploaded` with a `tiger_id`. Cases under `NOT synced` stayed `draft` — report them, do not silently drop.

Supersedes in this batch → old rows stay live. Full mechanics: `testcase-render` Sync section. Do not pass `--retire-superseded` without its own confirmation.

### Step 7b — Render .xlsx (explicit opt-in only)

Runs only when the user explicitly wants a sheet — **not** a fallback for a missing key or suite id. Missing prerequisite → 7c, not here.

Infer `--service` from the repo (`pom.xml` `<artifactId>`, else `package.json` name, else dir name). `--author` is the GDN username — reuse it if known this session, else ask once.

```bash
python3 {skill-dir}/../testcase-render/scripts/render_test_cases.py render \
  --input test-cases/ --jira <KEY> \
  --output test-cases-<KEY>.xlsx \
  --service <service> --author <gdn-username>
```

Skip and tell the user to render manually only when `--author` is unknown and they do not supply it, or `openpyxl` is missing. Never block case generation on the render.

**Do not mark uploaded on this path.** The script cannot verify the manual upload. Cases stay `draft`; the user uploads, then runs `testcase-render mark-uploaded --jira <KEY>` in a separate step. Sync path (7a) is different — the API confirms, so it marks them itself.

A per-ticket render produces a per-ticket Excel for the dev. The designated uploader still runs a full-service `testcase-render` (all drafts) when batching the sprint's tickets — the two do not conflict, because this one is `--jira`-scoped and neither marks uploaded.

### Step 7c — Missing prerequisite: ask user to fix

Reached when the key or suite id is missing and the user has **not** asked for a sheet. Deliver nothing; do not render.

- **No suite id** → discover, show candidates, ask user to fill `Test Tiger suite` in `~/.claude/references/component-map.md`. Never guess a number — wrong suite files cases under another squad.
  ```bash
  python3 {skill-dir}/../testcase-render/scripts/test_tiger_client.py projects --search <name>
  python3 {skill-dir}/../testcase-render/scripts/test_tiger_client.py suites <project-id>
  ```
- **`key_missing=true`** → ask user to generate + save a key themselves (`test_tiger_client.py setup --key <key>`). Never handle the key.

Cases are written to `test-cases/*.md` regardless. Once the user fixes the prerequisite, re-run delivery → 7a (sync). Report the block as a finding, not a failure.

## Step 8 — Report

Cases written, cases superseded, gaps found. Then per path:

| Path | Report | Next step for user |
|---|---|---|
| Sync (7a) | Synced count + `tiger_id` each, `NOT synced` list, superseded rows still live | Review diff, commit — cases already in Test Tiger |
| Render (7b) | Excel path (or why skipped) | Review diff, commit, upload Excel, then `mark-uploaded` |
| Blocked (7c) | Which prerequisite is missing (suite id / key), discovered candidates | Fix the prerequisite, then re-run delivery (7a) |

---

## Common Pitfalls

- **Reformatting untouched cases** — the fastest way to lose user trust. A ticket about token refresh must not touch 13 unrelated files.
- **Over-classifying AFFECTED** — an AC that adds behavior is `NEW`. `AFFECTED` only when an existing assertion becomes wrong.
- **Renaming an uploaded case** — name is the identity in the upload target. Rename = duplicate row. Supersede instead.
- **Silent supersede** — always show old vs new and ask. Superseding creates manual cleanup work in the target system; user must opt in.
- **Inventing error codes** — ticket says "returns an error" with no code → that is a gap, report it. Do not write `ERR_RATE_LIMIT` because it sounds right.
- **Guessing test_type** — ticket ambiguous between `NEW_FEATURE` and `REGRESSION` → ask. Enum rules in `{skill-dir}/../testcase-render/references/test-case-rules.md`.
- **Marking new cases `uploaded`** — they have not been uploaded. Always `draft`.
