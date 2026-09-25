---
name: testcase-render
description: >-
  Render test-cases/*.md into the GDN test-case upload .xlsx, or sync them
  straight into Test Tiger over its REST API. Use when asked to render,
  export, or generate the test case Excel, to upload/sync test cases to Test
  Tiger, or to mark test cases as uploaded. Handles draft cases only, since the
  xlsx upload target creates new rows and never updates.
---

# Test Case Render

## Announce Model

Print before any other output:
```
[testcase-render] Phase: deliver (mechanical — Haiku-suitable)
```

Wraps `scripts/render_test_cases.py` (.xlsx) and `scripts/sync_test_tiger.py` (Test Tiger). Scripts own the format and the API; this skill drives them.

Run from inside target project repo, not this skills repo.

## Two delivery paths

Same `test-cases/*.md` source. Pick by what target squad uses.

| Path | Command | Upload | Marks uploaded |
|---|---|---|---|
| **Sync** (default) | `sync_test_tiger.py` | Automatic, via Test Tiger API | Automatic — API confirms each case |
| **Render** (explicit opt-in) | `render_test_cases.py render` | Manual .xlsx upload by user | Separate `mark-uploaded` step |

Sync needs `TESTCASES_KEY` + suite id. Missing prerequisite → **stop, ask user to fix** (fill suite id in `component-map.md`, or generate + save key). **No auto-fall-back to render.** Render runs only when user explicitly asks for `.xlsx`. Never both for same case: sync marks `uploaded`, so later render skips it.

## Why drafts only

Both targets append. Re-delivering an uploaded case duplicates it. So:

- `status: draft` → renders / syncs
- `status: uploaded` → skipped
- retirement (supersede or `retire`) deletes the file after its target row goes — `delete-case` when `tiger_id` is known, by hand otherwise

Every render and every sync is a delta.

## Agent behavior

- **Never hand-write the .xlsx.** Always go through the script.
- **Never mark uploaded without confirmation** on render path. Script cannot verify the manual upload succeeded. Ask. Sync path exempt — API confirms each case.
- **Always surface the retire list.** Superseded rows stay live in the target until deleted.
- **Render path: do not upload anything.** Upload is manual, by the user.
- **Sync path: dry-run first.** Sync writes to a shared system. Show the plan, get a yes, then sync.
- **Never touch the key.** User generates and saves it. Do not read it, print it, or paste it into a command.

---

## Sync to Test Tiger (preferred path)

Pushes drafts straight into a Test Tiger suite. No manual upload, no .xlsx.

Self-contained. `scripts/test_tiger_client.py` owns auth and the handful of endpoints it needs; `sync_test_tiger.py` maps `.md` → payload and drives it. No plugin needed — this repo installs by copying directories and cannot declare that kind of dependency.

### S1 — Prerequisites

Key only. `TESTCASES_KEY` set, or saved config:

```bash
python3 {skill-dir}/scripts/test_tiger_client.py projects --search iam
```

`key_missing=true` → user generates one at https://test-tiger.gdn-app.com/account/detail and saves it **themselves**:

```bash
python3 {skill-dir}/scripts/test_tiger_client.py setup --key <their-key>
```

Never run that with a key they pasted in chat, never echo a key back. Saved to `~/.claude/.testcase-tiger.json`, chmod 600, survives skill reinstall.

TLS error mentioning `CERTIFICATE_VERIFY` → `python3 -m pip install --user certifi`. Client picks it up automatically.

### S2 — Resolve suite id

Which suite depends on what is being synced:

| Syncing | Target |
|---|---|
| A ticket's cases | the **release folder** for the release it ships in — see below |
| `<SERVICE>-BASE` baseline, standing regression | `Test Tiger suite` column in `~/.claude/references/component-map.md` |

**Release folder.** A ticket's cases belong under its release, not the default suite:

```
Release
  └── Deployment_iam_<DDMonYYYY>      e.g. Deployment_iam_27Jul2026
```

Derive from the release name — `IAM SP14.2607.27` → `27Jul2026` → `Deployment_iam_27Jul2026`. **DDMonYYYY**, matching the folders already in the tree. Never invent a different date format.

Ask which release the ticket ships in when it is not stated. Do not read it off the ticket's due date.

Suite id missing → **do not render**. Discover ids, ask user to fill `component-map.md`, then sync:

```bash
python3 {skill-dir}/scripts/test_tiger_client.py projects --search <name>
python3 {skill-dir}/scripts/test_tiger_client.py suites <project-id>
```

Show discovered candidates, ask user to confirm + record in the map so next run needs no question. Never guess a suite id, never fall back to `.xlsx`.

**Release folder is created for you.** Pass `--project-id`, `--parent-id` (the Release) and `--suite-name`; sync find-or-creates it. Idempotent — an existing folder is reused, never duplicated.

Match is on exact name under that parent, so a typo makes a second folder instead of reusing the right one. Dry-run first: it prints `exists → suite <id>` or `does NOT exist → would be created`, and creates nothing.

`test_tiger_client.py create-suite --project-id X --parent-id Y --name Z` does the same standalone.

Ambiguous tree → ask which suite. Never guess a suite id; wrong id files cases under another squad.

### S3 — Dry run first

```bash
# release folder, created if absent
python3 {skill-dir}/scripts/sync_test_tiger.py \
  --input test-cases/ --jira <KEY> --dry-run \
  --project-id <project> --parent-id <release> --suite-name Deployment_iam_<DDMonYYYY>

# or a suite id you already know
python3 {skill-dir}/scripts/sync_test_tiger.py \
  --input test-cases/ --suite-id <id> --jira <KEY> --dry-run
```

Prints payloads, writes nothing — including no folder. With a key it also diffs against the live suite — `+ create` / `~ update` per case. Show that. Get a yes.

### S4 — Sync

```bash
python3 {skill-dir}/scripts/sync_test_tiger.py \
  --input test-cases/ --jira <KEY> \
  --project-id <project> --parent-id <release> --suite-name Deployment_iam_<DDMonYYYY>
```

One pass per case. Title already in suite → update metadata. New title → create with steps. Full metadata goes in at creation: `## Summary` → description, `P0`/`P1` → `HIGH`, Jira key → label. Test Tiger's priority enum accepts only `HIGH`/`MEDIUM`/`LOW`; posting `CRITICAL` fails with HTTP 400.

Per case, script writes `tiger_id` and flips `draft` → `uploaded`. **Only cases API confirmed.** Failures and skipped duplicates stay `draft` and print under `NOT synced` — re-run retries exactly those, never double-creates the rest.

Exit 1 with a `NOT synced` list is partial success, not total failure. Read the list; do not re-run blindly assuming nothing landed.

`--mode auto-skip` leaves live duplicates alone instead of updating their metadata. Default `auto-update`.

### S5 — Retire superseded rows

Sync leaves superseded rows live and says so. Deleting is a separate, destructive opt-in:

```bash
python3 {skill-dir}/scripts/sync_test_tiger.py \
  --input test-cases/ --suite-id <id> --jira <KEY> --retire-superseded
```

Deletes old Test Tiger row (`DELETE /api/testCase/{id}`), then old local file, then clears pointer. **Confirm first** — show which cases and which ids.

Old case has no `tiger_id` (delivered through xlsx path before sync existed) → script cannot find its row. Prints it under `DELETE BY HAND`. Relay that; do not guess an id.

### S6 — Commit

`tiger_id` + `status` changes are the upload log. Commit them.

---

## Render path (explicit opt-in)

Manual .xlsx upload. **Not a fallback for missing sync prerequisites** — missing key or suite id → stop and ask user to fix, do not render. Use render only when user explicitly wants a sheet.

### Prerequisites

```bash
python3 -c "import openpyxl" 2>/dev/null || python3 -m pip install --user openpyxl
```

### Step 1 — Validate

```bash
python3 {skill-dir}/scripts/render_test_cases.py validate --input test-cases/
```

Fails → show the problem list, fix the `.md` files, re-run. Do not render over a validation failure.

Script rejects: missing frontmatter fields, missing body sections, bad `test_type`/`importance`/`status` enums, populated `actual_result`, duplicate `test_case` titles, `supersedes` pointing at a nonexistent file.

### Step 2 — Gather metadata

Needed: `service`, `author`. Optional: `version`.

Infer `service` from repo, confirm with user:

| Project type | Read |
|---|---|
| Maven | `pom.xml` `<artifactId>` |
| Node | `package.json` `name` |
| Neither | directory name |

`author` is the GDN username. Ask if unknown; do not guess from git config without confirming.

**Output filename** — depends on what is being rendered:

| Render | `--output` |
|---|---|
| One ticket (`--jira IAM-12130`) | `test-cases-IAM-12130.xlsx` |
| Whole service, all drafts | `test-cases-<service>.xlsx` — e.g. `test-cases-iam-rbac.xlsx` |
| Baseline only | `test-cases-<service>.xlsx` |

A full-service render mixes multiple tickets plus `<SERVICE>-BASE` cases, so it has no single ticket key — name it by service.

### Step 3 — Render

Whole service (designated uploader):

```bash
python3 {skill-dir}/scripts/render_test_cases.py render \
  --input test-cases/ \
  --output test-cases-<service>.xlsx \
  --service <service> \
  --version <version> \
  --author <gdn-username>
```

One ticket (per-dev, or invoked by `testcase-from-jira`):

```bash
python3 {skill-dir}/scripts/render_test_cases.py render \
  --input test-cases/ --jira <KEY> \
  --output test-cases-<KEY>.xlsx \
  --service <service> --author <gdn-username>
```

Script substitutes `Metadata` placeholders, renames the `service-name` tab, leaves Actual Result blank, and prints the retire list.

No drafts → script says so and writes nothing. Report that plainly; do not manufacture a file.

### Step 4 — Report

Give user:

1. Output path and case count
2. **Retire list** — old rows to delete manually in the test management system, if any
3. Reminder that Actual Result is intentionally blank

```
Rendered 3 cases → test-cases-IAM-12130.xlsx

  RETIRE MANUALLY (1):
    - IAM-11204 - Refresh returns same token
        superseded by IAM-12080-refresh-rotates.md

Actual Result blank — QA fills PASSED/FAILED at execution.
Next: upload the .xlsx, delete the superseded target row, then run mark-uploaded (which deletes the old file).
```

### Step 5 — Mark uploaded (separate turn)

Only after user confirms the upload happened.

```bash
# whole service (designated uploader, after a full-service render)
python3 {skill-dir}/scripts/render_test_cases.py mark-uploaded --input test-cases/

# one ticket only (per-dev, pairs with `render --jira <KEY>`)
python3 {skill-dir}/scripts/render_test_cases.py mark-uploaded --input test-cases/ --jira <KEY>
```

Flips matching `draft` → `uploaded`, and **deletes** every superseded old case file (its target row was already deleted by hand at render time; the pointer on the new case is cleared so validate stays green). `--jira <KEY>` scopes both render and mark-uploaded to one ticket — always pair them: render `--jira X`, upload that Excel, then mark-uploaded `--jira X`. Marking without the scope after a scoped render would flip teammates' drafts you never uploaded.

Ask first:

> Did the upload succeed? `mark-uploaded` flips {N} cases to `uploaded` — after that they never render again.

Never run this in the same turn as `render`. The script cannot see the test management system; only the user knows the upload landed.

Commit the change. Git history is the upload log.

---

## Retire a case — either path (behaviour removed, no replacement)

Superseding replaces a case with a new one. **Retiring deletes a case with no replacement** — the ticket removed the behaviour outright. Usually invoked by `testcase-from-jira`'s `REMOVED` verdict, but available directly:

```bash
# one case
python3 {skill-dir}/scripts/render_test_cases.py retire --input test-cases/ --case <file>.md

# a whole ticket's cases
python3 {skill-dir}/scripts/render_test_cases.py retire --input test-cases/ --jira <KEY>
```

The script prints the target rows to delete by hand (for cases already `uploaded`), then deletes the local `.md` file(s). A draft that was never uploaded is deleted with no target reminder — nothing was ever sent.

**Destructive — confirm first.** Show which cases and which target rows, get a yes. This is the only verb that deletes case files. Then commit the deletion.

---

## Common Pitfalls

- **Rendering all cases instead of drafts** — duplicates every previously uploaded case in the target system. Script guards this; do not work around it with `--input` pointed at a copy.
- **mark-uploaded before uploading** — cases go `uploaded` and never render again. Recovery is a manual frontmatter edit or `git revert`.
- **Ignoring the retire list** — superseded rows stay live. QA then sees two contradictory versions of the same test.
- **Editing the .xlsx by hand** — next render overwrites it. Edit the `.md` and re-render.
- **Swapping the template without checking headers** — script fails loudly with a diff rather than writing misaligned columns. Read that error; do not force past it.
- **Renaming a case file after upload** — breaks the supersede chain and duplicates on next upload.
- **Reading sync's exit 1 as "nothing synced"** — partial success is normal. Cases listed under `NOT synced` stayed `draft`; everything else landed. Re-run is safe.
- **Rendering .xlsx for cases already synced** — sync marks them `uploaded`, so render skips them. Correct. Do not force them back to `draft` to get a sheet.
- **Syncing without `--jira`** — sweeps every draft in the repo, including a teammate's. Scope it.
