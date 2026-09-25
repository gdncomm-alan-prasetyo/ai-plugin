---
name: testcase-baseline
description: >-
  Bootstrap QA test cases for a project that has none, from its integration
  tests and documentation. Use when asked to create a test case baseline, seed
  test cases, or invoked automatically by testcase-from-jira when no test-cases/
  directory exists. Scoped per module. Names baseline knowledge <SERVICE>-BASE.
  Also files a Jira to add integration tests where only unit tests exist.
  Always present a plan and get approval before writing files.
---

# Test Case Baseline

## Announce Model

Print before any other output:
```
[testcase-baseline] Phase: baseline generation
```

One-time per module. Reads integration tests and docs, writes `test-cases/*.md`. Baseline knowledge is named `<SERVICE>-BASE`.

Run from inside target project repo, not this skills repo.

## Field rules live in a reference file

Storage format, frontmatter fields, enums, coverage checklist: `{skill-dir}/../testcase-render/references/test-case-rules.md`.

Read that file **once, after plan approval** — before writing any case file.

If that file is missing, `render_test_cases.py validate()` is the schema authority — its checks define required frontmatter, section names, and enums. Do not guess; run validate to confirm. Planning steps below need none of it.

## Agent behavior

- **Always plan before writing.** Never plan and write files in same response.
- **Approval is explicit.** "yes", "go ahead", "approve", "looks good", "do it". Silence or a follow-up question is NOT approval.
- **Scope is mandatory.** Never baseline a whole repo in one run. Ask for module/package if user did not name one.
- **Never invent.** Every case traces to a real integration test, doc, or endpoint. Detail missing from sources → state the gap, do not fabricate.
- **Do not modify production or test code.** This skill writes `test-cases/*.md` and files Jira tickets only.
- **Do not render .xlsx.** That is `testcase-render`.
- **Confirm before filing Jira.** Integration-test-gap tickets are a side effect. Show them, get a yes, then create.
- All cases written as `status: draft`, `jira: <SERVICE>-BASE`.

---

## Phase 0 — Resolve service name

Baseline knowledge is keyed on the service, not a ticket. Derive it:

| Project | Read | Example |
|---|---|---|
| Maven | root `pom.xml` `<artifactId>` | `iam-rbac` |
| Node | `package.json` `name` | — |
| Neither | directory name | — |

`SERVICE = <artifactId>`. Baseline key = `<SERVICE>-BASE`, e.g. `iam-rbac-BASE`. Confirm with user before using.

This key becomes the `jira` frontmatter value and the filename prefix for every baseline case. It marks them as baseline-origin, distinct from ticket-origin cases.

## Phase 1 — Check for existing baseline

```bash
ls test-cases/*.md 2>/dev/null | wc -l
```

Count > 0 → baseline exists. Stop. Tell user:

> **Baseline exists** — `test-cases/` has {N} cases. Use `testcase-from-jira` for per-ticket work. Re-running baseline would duplicate coverage.

Only continue when count is 0, or user explicitly asks to extend baseline into a new module.

## Phase 2 — Determine scope

User named module → use it. Otherwise ask:

> Which module should I baseline? Full-repo baselines produce hundreds of cases and are not reviewable in one pass.
>
> Modules found: {list from `ls` or `pom.xml` `<modules>`}

Wait for answer.

## Phase 3 — Read sources (parallel, cheap model)

Sources:

| Source | Locate with | Gives |
|---|---|---|
| Integration tests | Grep `*IntegrationTest` in `src/test`, glob `*.java` | Real endpoints, payloads, status codes, error codes |
| Unit tests | Grep `*Test` (non-`*IntegrationTest`) in `src/test` | Error branches, exception paths — and which classes have unit but no integration coverage |
| Project `CLAUDE.md` | Read root | Domain model, Kafka topics, conventions |
| Architecture docs | Glob `**/*architecture*.md`, `docs/**/*.md` | Flows not visible in tests |
| Controllers / services | Grep `@RestController`, `@Service` in scoped module | Classes with no test coverage yet |

Integration tests are the strongest source: real paths, real request bodies, real assertions.

**Extraction is mechanical — route it to a cheap model, and fan out per controller.**

Reading N controllers serially on the capable model is the biggest cost in a full baseline (one real run: ~7 min, 151k tokens). This is pure reading, not judgement, and controllers are independent. So:

- Spawn **one Task subagent per controller/service** (use the Agent tool, `model: haiku`), in a single message so they run concurrently. Wall-clock drops to the slowest single file; each agent's context stays small.
- Each subagent returns a compact map for its file: endpoint → tested scenarios → exact status/error codes → `TESTED`/`PARTIAL`/`UNIT_ONLY`/`UNTESTED` verdict. Not the raw file.
- The capable (current) session does the authoring and classification in Phase 4+ from those maps. Do not read whole controllers into the main session.

Fewer than ~3 files in scope → skip the fan-out; read them directly.

## Phase 3b — Persist the coverage map

Write the merged per-controller maps to `.testcase-coverage.md` at repo root:

```markdown
# Coverage map — <SERVICE> (generated by testcase-baseline)
# endpoint → tested scenarios → exact codes → verdict

POST /api/user/create
  - happy path (Entra) → 200        [UserControllerIntegrationTest:88]  TESTED
  - tenant not configured → 400     [same]                              TESTED
GET /api/user/search
  - (unit only, UserServiceImplTest) UNIT_ONLY
```

`testcase-from-jira` reads this file to classify a ticket's ACs **without re-scanning every test** — the same context-cache pattern `be-review-context` uses for reviews. Regenerate it when tests change materially; stale is better than absent, but note the HEAD it was built at.

## Phase 4 — Build coverage map

Classify each endpoint/class in scope (from the Phase 3 subagent maps):

| Verdict | Meaning | Action |
|---|---|---|
| `TESTED` | Integration test exercises it | Write case from that test |
| `PARTIAL` | Integration test covers some branches | Write case per covered branch, list gaps |
| `UNIT_ONLY` | Has a unit test, **no integration test** | Report + queue a Jira to add integration tests (Phase 6) |
| `UNTESTED` | No test of any kind | List as gap. Do NOT invent a case. |

`UNIT_ONLY` is the actionable gap. The class has proven behaviour in a unit test but no end-to-end coverage — that is exactly what an integration-test ticket should target. `UNTESTED` is reported but not ticketed automatically; no test means no confirmed behaviour to base a ticket on.

## Phase 5 — Output plan

```
Module: iam-rbac-web    Service key: iam-rbac-BASE    Scope: 4 controllers, 11 endpoints

  From integration tests (will generate):
    + iam-rbac-BASE-user-search-success        POST /api/user/search     [REGRESSION/P0]
    + iam-rbac-BASE-user-create-entra          POST /api/user/create     [REGRESSION/P1]

  UNIT_ONLY — has unit test, no integration test (will file 1 Jira to add):
    ~ EntraServiceImpl        EntraServiceImplTest covers service; no *IntegrationTest
    ~ GoogleWorkspaceRestServiceImpl   unit only

  UNTESTED — no test at all (reported, not ticketed):
    ! DELETE /api/user/delete   no test found

Total: 2 cases. 2 classes need integration tests. 1 endpoint has no source.
```

Always show all three lists. Coverage gaps are as valuable as the generated cases.

**Wait for explicit approval** of the whole plan — cases AND the Jira. Then read `{skill-dir}/../testcase-render/references/test-case-rules.md` and write files.

## Phase 6 — Write files and file the Jira

### 6a — Baseline cases

One file per case: `test-cases/<SERVICE>-BASE-<slug>.md`.

Frontmatter `jira: <SERVICE>-BASE`, **`test_type: REGRESSION`** (baseline documents already-shipped behaviour, not new work — always REGRESSION, never NEW_FEATURE). All `status: draft`, `supersedes: null`.

Case name prefix uses the same key: `iam-rbac-BASE - Search users returns 200`.

**Writing many files — use a generator, not N Write calls.** A baseline can produce 100+ files. One Write per case round-trips full content through the model and is the single largest cost. Instead: author the case content **once** (in your response or a working structure), then emit all files with a throwaway Python script.

```bash
python3 - <<'PY'
cases = [
  {"slug": "user-search-success", "title": "iam-rbac-BASE - Search users returns 200",
   "jira": "iam-rbac-BASE", "test_type": "REGRESSION", "importance": "P0",
   "summary": "...", "preconditions": "...", "steps": "...", "expected": "..."},
  # ... one dict per case, authored per-case (NOT template-filled)
]
import pathlib, textwrap
for c in cases:
    body = f"""---
test_case: "{c['title']}"
jira: {c['jira']}
test_type: {c['test_type']}
importance: {c['importance']}
status: draft
supersedes: null
---

## Summary
{c['summary']}

## Preconditions
{c['preconditions']}

## Steps
{c['steps']}

## Expected Result
{c['expected']}
"""
    pathlib.Path(f"test-cases/{c['jira']}-{c['slug']}.md").write_text(body)
print(f"wrote {len(cases)} cases")
PY
```

The generator is a **write mechanism, not a licence to template-fill.** Every case's summary/steps/expected must still be authored per-case from its real integration test — same quality bar as writing by hand. Use the generator for >~15 cases; below that, individual Write calls are fine.

### 6b — Integration-test Jira

One ticket per baseline run listing every `UNIT_ONLY` class — not one ticket per class (that floods the backlog).

Derive the project key from the service's real Jira project (ask if unknown — `iam-rbac` → `IAM`). Confirm the ticket before creating.

```bash
JIRA_CLI=$(find ~/.claude/plugins/cache -path '*/jira-issues/*/scripts/jira_cli.py' 2>/dev/null | sort -V | tail -1)
python3 "$JIRA_CLI" create <PROJECT_KEY> Task "[<SERVICE>] Add integration tests for unit-only classes" \
  --labels "test-coverage,baseline" \
  --description "$(cat <<'EOF'
## Summary

Baseline of `<SERVICE>` found classes with unit tests but no integration test. Add integration coverage.

## Classes needing integration tests

- `EntraServiceImpl` — `EntraServiceImplTest` covers the service in isolation; no `*IntegrationTest` exercises it end to end
- `GoogleWorkspaceRestServiceImpl` — unit only

## How

Run `generate-tests` per class, or the `/test` command, to add `*IntegrationTest` coverage.
Filed automatically by testcase-baseline.
EOF
)"
```

Markdown, not wiki markup — the CLI converts markdown to ADF. Backtick class names so `_` is not eaten as italic.

Report the created ticket key. If the user declined the Jira, print the class list for manual filing.

## Phase 7 — Verify

```bash
python3 {skill-dir}/../testcase-render/scripts/render_test_cases.py validate --input test-cases/
```

Report: cases written, integration-test ticket key (or "declined"), UNTESTED count. Tell user next step is `testcase-render`, or `testcase-from-jira` for ticket work.

---

## Common Pitfalls

- **Baselining the whole repo** — produces an unreviewable pile. Scope per module, always.
- **Generating cases for untested endpoints** — no source means the case is invented. Report as gap instead.
- **One Jira per unit-only class** — floods the backlog. One ticket per run, listing all.
- **Filing the Jira without asking** — creating tickets is a side effect. Show the list, get a yes.
- **Ticketing UNTESTED classes** — no test means no confirmed behaviour to target. Only `UNIT_ONLY` gets a ticket.
- **Using a ticket key instead of `<SERVICE>-BASE`** — baseline cases have no originating ticket. The service key is their origin marker.
- **Copying test method names as case names** — `createFoo_validRequest_success` is a Java identifier, not a QA case name. Write `iam-rbac-BASE - Create foo with valid request returns 201`.
- **Losing the error code** — integration tests assert exact codes. Carry them into Expected Result; that is the detail QA cannot re-derive.
- **One case per test method** — a parameterized test with 5 inputs is often 5 cases. Split by scenario.
- **Marking baseline cases `uploaded`** — always `draft`.
- **`test_type: NEW_FEATURE` on baseline cases** — baseline documents shipped behaviour. Always `REGRESSION`.
