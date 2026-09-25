---
name: plan-to-jira-creation
description: >-
  Breaks down an approved implementation plan into Jira Tasks with a
  Development Sub-task (and a Testing Sub-task when test coverage is
  required) each. Groups by independent unit of work so different
  engineers can pick up different Tasks in parallel; keeps genuinely
  sequential steps together inside one Task instead of creating cross-Task
  dependencies. Sets the Test Case Required field based on whether the
  Task touches business logic. Creates the tickets via the jira-issues
  skill (Sub-tasks) and a direct Jira API call (Task, for the custom field).
---

# Plan to Jira Creation

Turn approved implementation plan into Jira tickets: one **Task** per
independently-workable unit of work, each with one **Development** Sub-task (plus
**Testing** Sub-task when required) under it. Does breakdown + creation — does not
judge plan quality; already settled before this runs.

## Role

When invoked, acts as careful ticket-creation assistant and executor:
- Follow approved plan. No inventing new scope.
- Resolve target Jira project before creating tickets.
- Ask explicit confirmation before any ticket creation.
- Create Sub-tasks through `jira-issues` CLI, Task through direct Jira API call.
  Report success/failure.

Uses `jira-issues` skill's CLI for Sub-tasks. Find it via:
```bash
find ~/.claude -path "*/jira-issues/scripts/jira_cli.py" 2>/dev/null | head -1
```
Call that path directly with `python3` — no re-derive Jira auth/API logic here.

## Step 1 — Resolve the plan

Look for plan, in order:
1. File path user just gave.
2. Most recently modified file under `~/.claude/plans/*.md` in this session.
3. Plan content already in conversation (e.g. just exited plan mode).

None found → stop, ask for plan (file path or pasted text). No guessing/inventing plan
content.

## Step 2 — Resolve target Jira project

Ask for project key if not obvious from context (active ticket key already mentioned
in session, or default project named in project memory/CLAUDE.md). Confirm before
creating anything — wrong project key means tickets in wrong place, expensive to undo.

If the user needs to look the key up, use the `jira-issues` CLI:
```bash
python3 {jira_cli_path} boards --minimal
python3 {jira_cli_path} search --my-open --minimal
```

## Step 3 — Split plan into independent units of work

Read plan's own structure — likely already groups by file/module/layer, or has
numbered implementation steps. Group changes by:
- Natural module/layer boundary (one Task per service, package, or repo touched), or
- Feature slice, if plan is one module with multiple independent behaviors.

**Independence check**, per candidate group (full worked examples in
`references/breakdown-checklist.md`):
- Can this be coded, tested, and PR'd without waiting on another group's code landing first?
- Does it need only stable *contract* from another group (interface, DTO shape, config
  key name) rather than that group's actual implementation?
- If group genuinely cannot start before another finishes (e.g. migration must exist
  before service reads new column) — do NOT split into two Tasks. Keep together in one
  Task, or merge smaller group into Task it depends on.

Never split down to single-file or single-line granularity. Task = meaningful,
reviewable, PR-sized chunk of work — not checklist item.

## Step 4 — Draft each Task

Per group:
- **Summary** — one line, action-oriented, names module/behavior. Not "Part 1",
  "Part 2", or anything only making sense next to other Tasks.
- **Description** — what changes, why (reuse plan's own stated context/reason if
  present), which files/areas touched (name directly, don't restate whole plan), how
  to verify Task independently (tests to run, endpoint to hit).
- **Payload** — if Task changes request/response body or event/message shape, add
  `Before:` / `After:` pair with field-level diff (added/removed/renamed fields, type
  changes). Skip if no payload changes.
- **Test Case Required** — Yes/No, decided per Step 4a. Required field on Task; create
  fails without it.
- **Sub-tasks**:
  - One **Development** Sub-task — title exactly `Development`, no summary appended.
    Actual coding happens here.
  - If Test Case Required = Yes, add **Testing** Sub-task — title exactly `Testing`.
    Skip when Test Case Required = No.
  - No other subtasks (no separate "review" subtask etc.) unless user explicitly asks.

### Step 4a — Decide Test Case Required per Task

`customfield_12575` ("Test Case Required") — required radio-button field (`Yes`/`No`)
on Task in this Jira project. Every Task create must set it.

Default **Yes** unless group's work clearly:
- Test-only changes (adding/fixing test coverage, no production code touched).
- Non-code changes (config-only, docs-only, infra/pipeline-only), no business logic or
  request/response behavior touched.

Otherwise — new/changed business logic, conditions, calculations, state transitions,
or request/response/event behavior — set **Yes**.

Unsure for a group → default **Yes**. Missing test case cheaper to catch in review than
skipped one.

## Step 5 — Confirm before creating anything

Print full list of proposed Tasks (summary + one-line description + Test Case
Required Yes/No + which Sub-tasks it'll get). Ask user to confirm or adjust grouping
(or flip any Yes/No call) before creating anything. Creating Jira tickets is
one-way, visible-to-others action — never skip this confirmation.

## Step 6 — Create

`jira-issues` CLI has no custom-field support (its own docs, out of scope) — do not
patch it. Call Jira REST API directly for Task create instead, reusing `jira-issues`'s
own auth client read-only. Locate it next to CLI path already resolved in Role section:
```bash
find ~/.claude -path "*/jira-issues/scripts/utils/jira_client.py" 2>/dev/null | head -1
```

Per confirmed Task, in order (not parallel — failure partway through must leave clean,
reportable partial state, not ambiguous one):

**6a — Task**, via small inline Python snippet importing `create_client` from located
`jira_client.py`, then:
```python
fields = {
    'project': {'key': PROJECT},
    'issuetype': {'name': 'Task'},
    'summary': SUMMARY,
    'description': {...ADF from DESCRIPTION...},
    'customfield_12575': {'value': 'Yes'},  # or 'No' — from Step 4a
}
client.post('issue', data={'fields': fields})
```
Read `key` from response — that's `{TASK_KEY}`.

**6b — Development Sub-task**, via normal `jira-issues` CLI (no custom field needed —
not required on Sub-task):
```bash
python3 {jira_cli_path} create {PROJECT} Sub-task "Development" --parent {TASK_KEY} --minimal
```

**6c — Testing Sub-task**, only if Test Case Required = Yes:
```bash
python3 {jira_cli_path} create {PROJECT} Sub-task "Testing" --parent {TASK_KEY} --minimal
```

Any create call fails → stop, report what succeeded so far, ask how to proceed. No
silent skip or retry loop.

## Step 7 — Report back

Table: Task key, summary, Test Case Required, Sub-task keys (Development / Testing) —
for everything created. Anything failed partway → say exactly which Tasks succeeded
and which missing, so user can retry just the gap.

## Constraints

- Never create Jira ticket without Step 5 confirmation.
- Never invent project key — ask or look it up.
- Never split work finer than reviewable, independently-testable chunk.
- Never make two Tasks that block on each other — merge into one Task instead.
- Never create Task without `customfield_12575` set — Jira rejects it (required field).
- Never patch `jira-issues` CLI for this — custom fields explicitly out of its scope;
  call Jira REST API directly instead.
