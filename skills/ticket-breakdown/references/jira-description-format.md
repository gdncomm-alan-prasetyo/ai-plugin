# Jira Description Format

Format the dev writes into the Jira **description** after tech discussion. Single source of truth for implementation and test cases.

Written by: `ticket-breakdown` phase 2, from your discussion answers.
Read by: `testcase-from-jira` (generates cases), dev (implements).

Shared by `ticket-breakdown` (tells dev what to write) and `testcase-from-jira` (parses it).

## Why this shape

Acceptance criteria in GIVEN / WHEN / THEN map 1:1 onto test case fields:

| AC part | Test case column |
|---|---|
| GIVEN | Preconditions |
| WHEN | Step Action |
| THEN | Expected Result |

So a well-written AC becomes a test case with no invention. A vague AC becomes a reported gap. The format is the contract between discussion and QA.

## Template

```
## Original request

> Rotate refresh token on every use. Old token invalid after rotation.
>
> _(verbatim, pre-grooming — kept for reference; sections below supersede it)_

---

## Summary

Rotate refresh token on every use. Old token invalid after rotation.

## Decisions

D1. Reused superseded token — revoke whole family, not just that request.
D2. Error code on expired refresh: AUTH_004 (no new code added).
D3. Existing rows: null supersededBy treated as not-superseded. No backfill.
D4. Applies to mobile clients too.

## Acceptance Criteria

AC-1. Refresh with valid token rotates
GIVEN active user with valid refresh token
WHEN POST /v1/auth/refresh with that token
THEN 200, response carries new refresh_token, old token marked superseded

AC-2. Expired refresh token rejected
GIVEN refresh token older than 30 days
WHEN POST /v1/auth/refresh with it
THEN 401, error code AUTH_004, no new token issued

AC-3. Reused superseded token revokes family
GIVEN refresh token already superseded by a rotation
WHEN POST /v1/auth/refresh with the superseded token
THEN 401, error code AUTH_004, every token in the family revoked

## Out of Scope

- Access token TTL change
- Mobile app release coordination

## Technical Notes

- RefreshToken entity gains supersededBy + index
- TokenServiceImpl.refresh owns rotation
- Config: auth.refresh.rotation.enabled, default true
```

`## Original request` sits **first**, blockquoted, so a reader sees the raw ask before the
groomed rewrite. It is mandatory — `edit --description` replaces the whole field, so the
prior text lives on only if carried forward. Jira changelog also retains prior descriptions.

## Rules

**Every AC gets an ID.** `AC-1`, `AC-2`. Test cases cite them. Renumbering after cases exist breaks traceability — append, do not renumber.

**THEN states exact values.** Status code, error code, field name. "Returns an error" is not testable — it becomes a gap. "401, error code AUTH_004" is.

**One behaviour per AC.** Two outcomes in one AC produce one muddled test case instead of two clean ones.

**Decisions keep their numbers** from the breakdown comment's open questions. `D2` answers question 2. Traceability from meeting to code to test.

**Decisions are not acceptance criteria.** A decision is a choice ("use AUTH_004"). An AC is testable behaviour. A decision usually shapes an AC's THEN clause; it is not one itself.

**Out of Scope is load-bearing.** Prevents scope creep in implementation and stops QA writing cases for things nobody built.

## Parsing

`testcase-from-jira` reads the `get` dump. Description is written as Markdown, stored as ADF, dumped back as Markdown — `##` round-trips intact.

AC live in a fenced code block so GIVEN/WHEN/THEN line structure survives that round-trip.

| Section | Used for |
|---|---|
| `Summary` | Case context |
| `Decisions` | Grounding. Authoritative over the original ticket text — decisions are newer. |
| `Acceptance Criteria` | One case per AC minimum, plus negative/boundary/permission derivations |
| `Out of Scope` | Do not generate cases for these |
| `Technical Notes` | Endpoint paths, config keys, entity names for step detail |

Missing `Acceptance Criteria` section → ticket not groomed. Report it, do not invent AC.

AC present but THEN vague → generate the case, flag the missing detail as a gap. Do not guess a status or error code.
