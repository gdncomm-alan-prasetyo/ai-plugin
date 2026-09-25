# Test Case Rules

Field rules transcribed from upload template's "How to fill" sheet. Renderer rejects payloads that violate them.

Shared by `testcase-baseline`, `testcase-from-jira`, `testcase-render`.

## Storage format

One case per file: `test-cases/<JIRA>-<slug>.md`.

```markdown
---
test_case: "IAM-12080 - Refresh with expired token returns 401"
jira: IAM-12080
test_type: NEW_FEATURE
importance: P0
status: draft
supersedes: null
---

## Summary
Verify expired refresh token is rejected.

Endpoint must return 401 with code TOKEN_EXPIRED and issue no new access token.

## Preconditions
User account exists and is active.
Refresh token issued more than 30 days ago is available.

## Steps
1. Authenticate as active user.
2. Use refresh token past its 30-day expiry.
3. POST /v1/auth/refresh with expired refresh_token.
4. Inspect response status, body, Set-Cookie headers.

## Expected Result
Response status is 401 Unauthorized.
Error code is TOKEN_EXPIRED.
No new access token issued.
No session cookie set.
```

Filename is the case's identity. Never rename a file whose `status` is `uploaded` — upload target creates new rows and never updates, so a renamed case uploads as a duplicate.

## Frontmatter fields

| Field | Required | Rule |
|---|---|---|
| `test_case` | yes | Descriptive name, ticket-key prefixed. Immutable once `status: uploaded`. |
| `jira` | yes | Ticket key. |
| `test_type` | yes | `NEW_FEATURE` / `REGRESSION` / `REGRESSION_SUPPORT` / `INTEGRATION` |
| `importance` | yes | `P0` / `P1` / `P2` / `P3` |
| `status` | yes | `draft` / `uploaded` / `retired` |
| `supersedes` | no | Filename this case replaces. `null` otherwise. |
| `author` | no | GDN username. Falls back to `--author`. |
| `tiger_id` | no | Test Tiger case id. Written by `sync_test_tiger.py`, never by hand. Numeric. Absent on cases delivered via .xlsx. |

`tiger_id` is what lets supersede and retire delete the remote row. Without it the row must be deleted by hand.

## Body sections

All four required. Section headings exact.

| Section | Maps to column | Rule |
|---|---|---|
| `## Summary` | Test Summary | Short summary, then detailed description. |
| `## Preconditions` | Preconditions | Background/assumptions. Empty body renders as `" - "`, never blank. |
| `## Steps` | Step Action | All steps, numbered, one cell. |
| `## Expected Result` | Expected Result | One line per scenario. |

Actual Result column always renders blank. QA fills PASSED/FAILED at execution. Renderer rejects any attempt to pre-fill it — pre-filling asserts a result for a test nobody ran.

## status lifecycle

Two delivery paths, same states.

```
draft ──sync──────────────────────────────────────> uploaded (+ tiger_id)
      └─render──> (manual upload) ──mark-uploaded──> uploaded
                                                        │
                          supersede (new case)  ────────┤──> old file DELETED
                          retire (no replacement) ──────┘    (row: delete-case if
                                                              tiger_id, else by hand)
```

- `draft` — not yet delivered. Only drafts render or sync. Delete freely (just remove the file); nothing downstream exists.
- `uploaded` — lives in test management system. Never re-render or re-sync; either duplicates it.
- Sync marks `uploaded` itself — API confirms each case. Render cannot, so `mark-uploaded` is a separate user-confirmed step.
- Sync marks **only confirmed cases**. Skipped duplicates and API errors stay `draft`, so a re-run retries exactly those.
- Retirement always ends with the **file deleted**, never a lingering `retired` file:
  - **supersede** — a new draft carries `supersedes: <old>`. Render lists the old target row to delete; `mark-uploaded` then deletes the old file and clears the pointer.
  - **retire** — behaviour removed, no replacement. `retire` prints the old target row to delete, then deletes the file.
- `retired` remains a valid status value but is transient; files do not linger in it.

## Test Type selection

Verbatim from template:

- `NEW_FEATURE` — JIRA is new feature.
- `REGRESSION` — JIRA is tech debt, or test only needs regression.
- `REGRESSION_SUPPORT` — JIRA is regression support request from another squad.
- `INTEGRATION` — JIRA involves collaboration with another squad. Add this type as well so QA can support testing.

`INTEGRATION` is additive. Ticket both new feature and cross-squad → emit separate `INTEGRATION` case covering the cross-squad contract. Do not drop either signal.

Infer from issue type, labels, components, description. Genuinely ambiguous → ask. Do not guess.

**Baseline cases are always `REGRESSION`.** They document behaviour already shipped and covered by existing integration tests — never new work. `testcase-baseline` sets `REGRESSION` unconditionally; do not use `NEW_FEATURE` for a `<SERVICE>-BASE` case.

## Importance selection

- `P0` / `P1` — High. Main flow and important.
- `P2` — Medium.
- `P3` — Low.
- Default High.

Mapping: happy path and auth/permission enforcement → `P0`. Significant alternate flows and common errors → `P1`. Edge/boundary → `P2`. Cosmetic or rare paths → `P3`.

## Coverage checklist

Cover in order:

1. **Happy path** — one per acceptance criterion.
2. **Alternate flows** — each explicit branch in AC.
3. **Negative** — invalid input, missing required fields, malformed payloads.
4. **Boundary** — empty, max length, zero, off-by-one, pagination limits.
5. **Permission/auth** — unauthenticated, wrong role, expired token, cross-tenant.
6. **Error handling** — downstream timeout/5xx, DB unavailable, partial failure.
7. **Regression risk** — existing behavior the change could break.

## Grounding

Every case grounded in real source: ticket, integration test, or project docs.

Never invent endpoints, field names, roles, error codes, or status codes not present in those sources. Coverage area needs a detail the sources omit → state the gap. Do not fabricate.

Steps must be executable by someone who has not read the ticket. `POST /v1/tokens with expired refresh_token` beats `test the token endpoint`.
