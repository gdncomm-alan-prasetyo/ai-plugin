---
name: ticket-breakdown
description: >-
  Two-phase Jira ticket grooming. Phase 1 (before tech discussion) analyses the
  ticket against the repo and posts impact, proposed changes, and open questions
  as a Jira comment. Phase 2 (after discussion) takes your answers, posts the
  settled breakdown, and rewrites the description with acceptance criteria that
  testcase-from-jira and implementation both read. Sprint sweep mode breaks down a
  whole sprint at once, filtered to tickets flagged Test Case Required = Yes. Use for
  "break down IAM-1234", "analyze ticket", "prepare for tech discussion", supplying
  discussion answers, or "break down the sprint" / "groom sprint <name>".
---

# Ticket Breakdown

## Announce Model

Print before any other output:
```
[ticket-breakdown] Phase: ticket analysis
```

Jira is the single source of truth. No local doc.

Run from inside target service repo, not this skills repo.

## Two phases, auto-detected

```
PHASE 1  before tech discussion
  analyse repo → post COMMENT: proposed changes + open questions

PHASE 2  after tech discussion
  your answers → post COMMENT: settled breakdown
               → rewrite DESCRIPTION: Summary / Decisions / AC / Out of Scope / Technical Notes

testcase-from-jira and implementation both read the description
```

Detect phase by scanning existing comments for the marker `_ticket-breakdown_`:

| Found | Phase |
|---|---|
| No breakdown comment | 1 |
| Phase-1 comment, no phase-2 comment | 2 |
| Phase-2 comment already exists | 2 again — re-groom. Warn that description will be rewritten. |

User supplies answers with no prior comment → run phase 1 analysis silently, then phase 2. Do not post the phase-1 comment; discussion already happened.

---

## Sprint sweep — multi-ticket mode

One sprint, many tickets, Phase 1 on each. Triggers: "break down the sprint", "groom sprint <name>", "breakdown all tickets in the sprint".

Scoped to tickets flagged **`Test Case Required = Yes`** — those are the ones a breakdown feeds downstream, since `qa-analyst` turns their AC into test cases next.

### W1 — Resolve the sprint, exactly

Need the **full sprint name as Jira spells it** — `IAM GAP WEEK JULY 2026`, not a short code. Not given → ask. Do not guess.

Short codes are a trap. `sprint = "SP14"` matches sprints of that name on *every* board, across years — it returns tickets from IAM-1978 through IAM-8878, nearly all closed and belonging to other squads. Jira matches sprint names loosely and project IAM is shared (CAS, MEMBER, ULP, PY-WHATSAPP, IAM-RBAC, TENANT-AUTH…). A vague name silently sweeps the wrong work.

`openSprints()` does not help — IAM tickets carry sprints but the project usually has none in an open state, so it returns nothing. Board lookup does not help either: `boards` caps at 50 and none match IAM by name.

User has the numeric sprint id (from the board URL) → prefer `sprint = <id>`. Unambiguous.

### W2 — Sanity-check, then filter

Two queries. The first proves the sprint resolved to what the user meant:

```bash
JIRA_CLI=$(find ~/.claude/plugins/cache -path '*/jira-issues/*/scripts/jira_cli.py' 2>/dev/null | sort -V | tail -1)

# 1. whole sprint - does the count and shape look right?
python3 "$JIRA_CLI" search \
  'project = IAM AND sprint = "<SPRINT NAME>" ORDER BY key ASC' --limit 50

# 2. the sweep set
python3 "$JIRA_CLI" search \
  'project = IAM AND sprint = "<SPRINT NAME>" AND "Test Case Required" = Yes AND status != Closed ORDER BY key ASC' \
  --limit 50
```

Query 1 comes back mostly old and closed → wrong sprint. Stop and re-ask; do not sweep.

`"Test Case Required"` is a custom field, values `Yes` / `No`. Quote the field name — unquoted it is a JQL syntax error. It is **not** a component; `component = "Test Case Required"` returns nothing.

`status != Closed` matters: a flagged sprint typically carries finished work. On a real run, 6 tickets were flagged and only 2 were still open. Breaking down a closed ticket posts a comment nobody reads.

Check `is_last` in the output. `is_last=false` → more results than `--limit` showed; raise it rather than sweeping a truncated set silently.

Count 0 → report plainly. Check the sprint name first, then whether any ticket carries the flag. Do not widen the filter to manufacture results.

### W3 — Show the list, get one approval

Never sweep without it. Phase 1 posts a Jira comment per ticket — N tickets is N comments on work other people own.

```
Sprint "IAM GAP WEEK JULY 2026" — 40 tickets, 6 flagged Test Case Required = Yes,
2 still open (4 closed, skipped)

  IAM-11203  [CAS] Reduce data size of TGT and Refresh Token    Open             not groomed
  IAM-11597  [PY-WHATSAPP] Migrate to Project Loom              In Development   not groomed

  Phase 1 posts a breakdown comment on each. Break down both, one, or cancel?
```

Show the funnel — sprint total, flagged, open — so a filter that silently ate everything is visible.

Mark each ticket's state so the user can skip what is already done:

| State | Meaning |
|---|---|
| `not groomed` | No `_ticket-breakdown_` comment → Phase 1 applies |
| `groomed` | Phase-1 comment exists → skipping is usually right; re-running re-posts |
| `settled` | Phase-2 comment exists → leave it; a sweep must not rewrite settled descriptions |

Default the selection to `not groomed` only. Wait for the answer.

### W4 — Run Phase 1 per approved ticket

Sequentially, each ticket its own full Phase 1 (§PHASE 1 below): map impact in its repo, post its comment.

Resolve each ticket's repo through `~/.claude/references/component-map.md` — a sprint spans components, so the repo changes per ticket. Follow its **§Resolving a repo**: find the checkout by matching `origin` against the row's `Repo URL` under `$IAM_WORKSPACE_ROOT`, never by directory name.

| Repo state | Do |
|---|---|
| Cloned locally | Verify it is the right remote and not stale (see the map's §Resolving a repo), then map impact |
| Mapped, not cloned | **Ask** — name the repo and ticket, ask whether to clone and where. Never clone silently. |
| User declines the clone | Skip that ticket, report it, keep going |
| Component unmapped | Skip that ticket, report it, keep going |

Batch the clone question. Four un-cloned repos is one question listing four, not four separate interruptions.

One unknown or un-cloned repo must not abort the sweep. A ticket that fails mid-sweep → record and continue. Report failures at the end; never leave the user guessing which of N landed.

### W5 — Report

```
Swept "IAM GAP WEEK JULY 2026" — 1 of 2

  posted    IAM-11203  iam-cas
  skipped   IAM-11597  gdncomm/py-whatsapp not cloned, declined
  failed    IAM-11291  component CECP not in component-map
```

Sweep never runs Phase 2. Phase 2 needs the tech-discussion answers, which are per-ticket and human. Say so, and hand back the list to groom individually.

---

## Agent behavior

- **Post directly for one named ticket.** Both comments post without a confirmation gate. That is the skill's purpose.
- **Sprint sweep is the exception.** One approval on the ticket list before any comment posts. The user named a sprint, not each ticket.
- **Preserve the original description.** Phase 2 rewrite puts the pre-existing description text first, blockquoted, under `## Original request`. `edit --description` replaces the whole field; never lose what was there.
- **Never invent an answer.** Unanswered question → the AC depending on it is not written. Flag it in the comment instead.
- **Propose AC when the ticket has none.** Phase 1 drafts them, marks them `(proposed)`, and raises a question asking the team to confirm. A concrete draft beats an abstract question. Never present a proposal as agreed.
- **Every AC traces to a decision or an explicit ticket line.** No trace → not an AC.
- **Never write code.** This skill writes Jira comments and one description.
- **Markdown, not Jira wiki markup.** The CLI runs `adf_from_text` (markdown → ADF). Wiki markup renders as literal text. See §Jira formatting.

---

## Jira formatting

`jira_cli.py` converts **Markdown** to ADF. Only these survive:

| Want | Write | Not |
|---|---|---|
| Heading | `### Text` | `h3. Text` |
| Bold | `**text**` | `*text*` |
| Bullet | `- item` | — |
| Numbered | `1.` `2.` | `#` (that is H1) |
| Rule | `---` | `----` |
| Code / identifier | `` `USER_CREATE` `` | bare `USER_CREATE` |

**No table support.** `||header||` and `|---|` both render literally. Use a bullet per row instead.

**Always backtick identifiers and paths.** `_` is italic in markdown — bare `USER_CREATE / UPDATE_STATUS` renders as `USERCREATE / UPDATESTATUS`, silently corrupting names.

**Put GIVEN/WHEN/THEN blocks in a fenced code block.** Consecutive plain lines collapse into one paragraph. A fence preserves line structure exactly, and survives the ADF round-trip so `testcase-from-jira` can parse it.

## Step 0 — Route, fetch, detect phase

Sprint named instead of a ticket key → §Sprint sweep. Otherwise single-ticket, below.

Accept key or browse URL. Extract key.

```bash
JIRA_CLI=$(find ~/.claude/plugins/cache -path '*/jira-issues/*/scripts/jira_cli.py' 2>/dev/null | sort -V | tail -1)
python3 "$JIRA_CLI" get <ISSUE-KEY>
```

`$JIRA_CLI` empty or `JIRA_URL`/`JIRA_TOKEN` unset → say so, ask user to paste ticket. Cannot post; print text for manual paste.

Read the dump's Comments section. Detect phase per table above.

Note the current description verbatim. Phase 2 needs it.

---

# PHASE 1 — before tech discussion

## 1.1 Map impact in repo

Extract nouns from ticket: entities, endpoints, fields, events, config keys.

Locate each. Grep, do not assume:

| Looking for | Grep |
|---|---|
| Endpoint | `@RequestMapping`, `@PostMapping`, path constant |
| Entity | class name, `@Document`, `@Entity` |
| Service method | method name, interface |
| Kafka event | topic constant, `@KafkaListener` |
| Config | key in `application*.yml`, `@ConfigurationProperties` |

Found → record `path/File.java:line`.
Not found → open question. Ticket names something the repo lacks; that needs deciding.

Read project `CLAUDE.md` for domain model and conventions.

Title and description disagree → that is question 1, and say which readings the code supports.

## 1.2 Derive proposed changes and open questions

Proposed change ties to a ticket line. No tie → `Out of scope`.

Question is real when the ticket does not answer it AND the answer changes implementation or tests:

| Source | Example |
|---|---|
| Missing error code | "return an error" — which code? |
| Missing boundary | "expire old tokens" — after how long? |
| Missing component | needs revoke; no revoke method exists — add or reuse? |
| Ambiguous scope | all clients or just mobile? |
| Migration unknown | existing rows need backfill? |
| Contract impact | response field added — breaking for consumers? |
| Default behaviour | unset property — allow or deny? |

Not a question: anything the ticket answers, anything answerable by reading the repo, anything phrased "should we do this properly".

Number them. Phase 2 answers by number.

## 1.3 Propose acceptance criteria

Check the description for an existing `Acceptance Criteria` section.

Exists → skip this step. Ticket is already groomed; do not rewrite the team's criteria.

**None → propose them.** Derive from ticket intent plus what the repo shows. Format per `{skill-dir}/references/jira-description-format.md` — GIVEN / WHEN / THEN, one behaviour each, ids `AC-1`, `AC-2`.

A concrete wrong AC is better meeting input than an abstract question. Team corrects a draft faster than it writes one from nothing.

Rules:

- Mark the whole block `(proposed)`. These are not agreed criteria until discussion confirms them.
- **The proposal is itself an open question.** Add a numbered question asking the team to confirm, correct, or extend the set.
- A `THEN` needing a value nobody has decided (status code, error code, threshold) → write `TBD` and raise its own numbered question. Never invent a code to make an AC look finished.
- An AC that depends entirely on an unanswered question → do not write it. Say which question blocks it.
- Cover the happy path plus the negative and permission cases the ticket implies. Do not pad with edge cases the ticket never suggests.

Phase 2 promotes confirmed AC into the description. Unconfirmed ones do not survive.

## 1.4 Post the comment

```
### Breakdown — _ticket-breakdown_

**Reading of the ticket**

(only when title and description disagree)

**Impacted components**

- **TokenService** `service/.../TokenServiceImpl.java:142` — rotation + invalidation
- **RefreshToken** `entity/.../RefreshToken.java` — needs `supersededBy`

**Not found in repo** — needs deciding, not assuming

- No revoke method on `TokenStore`

**Proposed changes**

1. `TokenServiceImpl.refresh` issues new token, marks old superseded
2. `RefreshToken` gains `supersededBy` + index

**Proposed acceptance criteria** — ticket has none; confirm, correct, or add

```
AC-1. Refresh with valid token rotates
GIVEN active user with valid refresh token
WHEN  POST /v1/auth/refresh with that token
THEN  200, new refresh_token returned, old marked superseded

AC-2. Expired refresh token rejected
GIVEN refresh token older than 30 days
WHEN  POST /v1/auth/refresh with it
THEN  401, error code TBD (see Q2), no new token issued
```

**Open questions**

1. Reused superseded token — revoke family, or reject that request only?
2. Error code on expired refresh? Repo has no `TOKEN_EXPIRED`; nearest `AUTH_004`. Blocks AC-2 THEN.
3. Proposed AC-1..AC-2 — confirm, correct, or add missing. Unconfirmed AC produce no test cases.

---
After discussion, run `ticket-breakdown` again with the answers.
```

Omit the proposed-AC section and its confirmation question when the description already has acceptance criteria.

```bash
python3 "$JIRA_CLI" comment <ISSUE-KEY> "$(cat <<'EOF'
<comment text>
EOF
)"
```

Report: ticket URL, component count, question count, posted.

---

# PHASE 2 — after tech discussion

## 2.1 Collect answers

Read open questions from the phase-1 comment.

User supplied answers → map to question numbers.
Not supplied → print the questions and ask for them. Accept freeform ("1. both in scope, 2. only createUser").

No open questions existed → skip straight to 2.2.

Answer missing for a question → do not guess. Mark `UNRESOLVED`. Any AC depending on it is not written.

## 2.2 Settle acceptance criteria

Read `{skill-dir}/references/jira-description-format.md` for the format and the AC → test case mapping.

Phase 1 proposed AC → start from those. Apply corrections from the answers. Drop any the team rejected. Add any they asked for. Keep confirmed ids stable.

Phase 1 proposed none (ticket already had AC) → use the description's existing AC, corrected by decisions.

One AC per distinct testable behaviour. Each traces to a decision or an explicit ticket line.

`THEN` states exact values — status code, error code, field name. A decision that named a code puts that code in the THEN. No decision on a code → write the AC, mark the THEN `TBD`, and list it as a remaining gap.

Number `AC-1`, `AC-2`. Never renumber later; append.

## 2.3 Post the settled comment

```
### Final breakdown — _ticket-breakdown_

**Decisions**

1. Revoke whole family, not just that request.
2. `AUTH_004`. No new code added.

**Acceptance criteria written** — AC-1 .. AC-3 (see description)

**Still unresolved**

- Q5 rate-limit threshold — AC not written

---
Description updated. `testcase-from-jira` and implementation read it from there.
```

## 2.4 Rewrite the description

Build per `{skill-dir}/references/jira-description-format.md`. Original request goes **first**, blockquoted, so a reader sees the raw ask before the groomed rewrite:

```
## Original request

> <the description exactly as it was before this rewrite>
>
> _(verbatim, pre-grooming)_

---

## Summary
...

## Decisions
D1. ...

## Acceptance Criteria
(fenced block — preserves GIVEN/WHEN/THEN line structure)
\`\`\`
AC-1. <title>
GIVEN <state>
WHEN  <action>
THEN  <outcome with exact status and code>
\`\`\`

## Out of Scope
- ...

## Technical Notes
- Impacted: `<paths>`
```

```bash
python3 "$JIRA_CLI" edit <ISSUE-KEY> --description "$(cat <<'EOF'
<description text>
EOF
)"
```

`edit --description` replaces the whole field. The leading `## Original request` block is why nothing is lost. Jira changelog also retains prior descriptions.

Report: AC count, decision count, unresolved count, description updated.

Tell user: run `testcase-from-jira` next.

---

## Common Pitfalls

- **Sweeping on a short sprint code.** `sprint = "SP14"` matches that name on every board across years. Use the full Jira name, or the numeric id.
- **Sweeping closed work.** Most flagged tickets in a finished sprint are done. Keep `status != Closed`.
- **Silent truncation.** `is_last=false` means the sweep saw only part of the sprint. Raise `--limit`; do not report a partial set as the whole.
- **Posting N comments without asking.** One named ticket is consent for one comment, not for a sprint's worth.
- **Cloning without asking.** A repo the user has not checked out is not an invitation to clone it. Ask, batched, and skip the ticket if they decline.
- **Analysing a stale checkout.** Right remote is not enough — a checkout hundreds of commits behind gives shifted line numbers and missing features, so every grounded claim in the comment is wrong. Check before citing.

- **Losing the original description** — always lead with a `## Original request` block. `edit` replaces the whole field.
- **Writing an AC for an unanswered question** — that is inventing a decision. Mark UNRESOLVED, skip the AC.
- **Proposed AC presented as settled** — always mark `(proposed)` and raise the confirmation question. Team must be able to tell a draft from a decision.
- **Overwriting AC the team already wrote** — description has an Acceptance Criteria section → skip step 1.3 entirely.
- **Padding proposed AC with invented edge cases** — cover what the ticket implies. Speculative criteria get rejected and cost trust.
- **Vague THEN** — "returns an error" is not testable and becomes a QA gap. Push for the code during discussion, or mark TBD.
- **Renumbering AC on re-groom** — test cases cite AC ids. Append only.
- **Wiki markup in Jira** — `h2.` and `||header||` arrive as literal text. The CLI wants Markdown: `##`, `**bold**`, `- bullet`. No tables (§Jira formatting).
- **Ungrounded impact table** — a component with no file path is a guess. Grep or drop it.
- **Padding questions** — 4 real ones beat 12 with 8 rhetorical. Team stops reading a padded list.
- **Decisions treated as acceptance criteria** — a decision is a choice; an AC is testable behaviour. A decision usually shapes a THEN.
