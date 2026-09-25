# Breakdown Checklist & Examples

## Independence checklist

Answer all four per candidate Task. Any "no" → reconsider split.

| # | Question | If "no" |
|---|----------|---------|
| 1 | Can this be coded, tested, and PR'd without another group's code landing first? | Merge into the Task it depends on |
| 2 | Does it need only a stable *contract* (interface, DTO shape, config key name) from another group, not that group's actual implementation? | Merge into the Task it depends on |
| 3 | Is it big enough to be a meaningful, reviewable PR — not a single file or single line? | Merge with a sibling group in the same area |
| 4 | Does its summary read as a standalone piece of work, not "Part 1 of 3"? | Rewrite the summary to name the actual behavior/module |

## Worked example — plan touching 3 backend layers, all independent

Plan: add a new notification channel. Touches:
- `NotificationEvent` model (new fields)
- `NotificationService` (new branch to send via new channel)
- `NotificationController` (new REST endpoint to trigger it)

All three only need stable contract from each other (model's field names, service's
method signature) — none needs *other's finished implementation* to be coded and
tested (mocks/stubs suffice). Split into 3 Tasks:

- Task A: "Add new channel fields to NotificationEvent model" — Test Case Required: No
  (model field addition, no business logic)
  - Sub-task: "Development"
- Task B: "Send notifications via new channel in NotificationService" — Test Case
  Required: Yes (new branching logic)
  - Sub-task: "Development"
  - Sub-task: "Testing"
- Task C: "Expose new channel trigger endpoint in NotificationController" — Test Case
  Required: Yes (new request/response behavior)
  - Sub-task: "Development"
  - Sub-task: "Testing"

## Worked example — genuine sequential dependency, stays as ONE Task

Plan: add a new DB column, then read it in a service.
- Migration: add `PREFERRED_LANGUAGE` column to `USER` table.
- Service: read `PREFERRED_LANGUAGE` when composing a message.

Service change can't be meaningfully tested until column exists — not contract
dependency (interface/DTO), real runtime dependency on other piece existing. Do NOT
split into two Tasks. Keep as one:

- Task: "Add and use PREFERRED_LANGUAGE column for message composition" — Test Case
  Required: Yes (new logic reading the column)
  - Sub-task: "Development"
  - Sub-task: "Testing"

## Task description template

```
Summary: {one line, action-oriented, names the module/behavior}
Test Case Required: {Yes/No — Step 4a}

Description:
What: {what changes}
Why: {why — reuse the plan's own stated reason if present}
Touches: {files/areas, named directly, not the whole plan restated}
Payload: {Before: <shape> / After: <shape> — only if request/response/event payload changes, else omit}
Verify: {tests to run, or endpoint/flow to exercise, to confirm this Task alone works}
```

Sub-task titles are fixed, no template needed: `Development` always; `Testing` only
when Test Case Required = Yes.
