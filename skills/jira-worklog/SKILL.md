---
name: jira-worklog
description: >-
  Tracks how long AI works on a Jira ticket and logs the time as a Jira
  worklog entry on the correct Sub-task. Detects whether the mentioned issue
  key is a parent Task or a Sub-task; auto-picks the right Sub-task only when
  exactly one exists, else asks. Starts timing
  when work on a ticket begins, stops and logs (after user confirms) when
  work wraps up, a PR opens referencing the ticket, or the user says so
  explicitly. Supports pause/resume/status/cancel. Worklog comment includes an
  actual-token rollup from the Claude Code transcript (excludes cache-read
  tokens, which inflate the raw total far past real work done), for tracking
  AI usage over time. Requires jira-issues plugin (JIRA_URL/JIRA_TOKEN) —
  worklog write goes via direct Jira API call, since jira-issues CLI has no
  worklog command.
---

# Jira Worklog

Tracks time spent on Jira ticket. Logs worklog on right Sub-task when work wraps up.
Never posts without confirm — worklog visible to whole team.

## Requires

- `jira-issues` plugin installed, `JIRA_URL` + `JIRA_TOKEN` set.
- No worklog command in `jira-issues` CLI — this skill posts directly via Jira REST
  API, reusing `jira-issues`' own auth client (`jira_client.py`). Never patch
  `jira-issues` CLI for this — out of its scope.

## Locate jira_client.py

Once per invocation:

```bash
find ~/.claude -path "*/jira-issues/scripts/utils/jira_client.py" 2>/dev/null | head -1
```

Not found → stop, tell user `jira-issues` plugin missing.

## Locate python interpreter

Once per invocation. `python3` broken on some Windows setups (Store alias stub, no
real interpreter behind it). Try in order, use first that runs as `{python_cmd}` for
every script call below:

```bash
python3 --version
py --version
python --version
```

None work → stop, tell user no Python interpreter found.

## Args / modes

- `start <KEY>` — begin tracking. `<KEY>` = whatever ticket key user mentioned (parent
  or Sub-task).
- `status [KEY]` — show elapsed time so far. Read-only, no Jira write.
- `pause <KEY>` / `resume <KEY>` — exclude idle stretch from logged time.
- `log [KEY]` — compute duration, confirm with user, post worklog, clear tracking.
- `cancel <KEY>` — drop tracking, no Jira write.

No `<KEY>` given, exactly one ticket tracked this session → use it. Multiple tracked,
none named → ask which.

## Step 1 — Resolve parent vs Sub-task

```bash
{python_cmd} {skill_dir}/scripts/worklog.py resolve <KEY> --jira-client {jira_client_path}
```

Output: `is_subtask`, and if parent, every Sub-task (`key|summary|status`) plus
`auto_target` when resolvable without asking.

- `is_subtask=true` → target = `<KEY>` itself. Done.
- `is_subtask=false`, `auto_target` set (only one Sub-task exists) → target =
  `auto_target`. Tell user which one picked — lets them correct if wrong.
- `is_subtask=false`, `auto_target` empty, `subtask_count=0` → no Sub-task exists.
  Ask user: log against parent directly, or stop and create Sub-task first.
- `is_subtask=false`, `auto_target` empty, `subtask_count>0` → ambiguous.
  `AskUserQuestion` listing every Sub-task (key + summary + status), let user pick.

## Step 2 — start

```bash
{python_cmd} {skill_dir}/scripts/worklog.py start <TARGET_KEY> --parent <PARENT_KEY> --from-key <KEY> --note "<one-line task description>"
```

`already_tracking=true` in output → already running, don't reset clock. Confirm
still tracking + elapsed so far.

## Step 3 — pause / resume

Straight passthrough:

```bash
{python_cmd} {skill_dir}/scripts/worklog.py pause <TARGET_KEY>
{python_cmd} {skill_dir}/scripts/worklog.py resume <TARGET_KEY>
```

Use when user steps away mid-task, or switches to a different ticket for a while —
keeps logged time to actual work, not idle/other-ticket time. Second ticket named
while first still active → pause first automatically, start second, tell user both
in one line ("paused IAM-100, now tracking IAM-200").

## Step 4 — log (compute → confirm → post)

1. Compute duration:
   ```bash
   {python_cmd} {skill_dir}/scripts/worklog.py compute <TARGET_KEY>
   ```
2. `too_short=true` (under 1 minute) → discard silently via `discard`, tell user
   nothing logged (too short to matter). Stop here.
3. Compute token usage over same active window:
   ```bash
   {python_cmd} {skill_dir}/scripts/worklog.py tokens <TARGET_KEY>
   ```
   Use `actual_tokens` (output + input + cache_creation) for the rollup —
   `cache_read_tokens_excluded` deliberately left out, since cache re-reads every
   turn and would inflate the number far past real work done. Round to nearest k
   for display (e.g. `actual_tokens=858864` → `~859k`).
4. Draft one-line work summary from what actually happened this session
   (implementation, fix, review — whatever the conversation shows). Not a restated
   ticket title. Append token rollup: `<summary> | ~<actual>k tokens (~<output>k
   output)`.
5. Show user: target key, computed duration, drafted comment (with token line),
   start time. Ask to confirm, edit duration/comment, or cancel — worklog posts are
   visible to whole team, never post unconfirmed.
6. Confirmed → post:
   ```bash
   {python_cmd} {skill_dir}/scripts/worklog.py post <TARGET_KEY> --jira-client {jira_client_path} --time-spent "<duration>" --comment "<comment>"
   ```
   Report success + duration logged + issue key.
7. Cancelled → leave tracking as-is, state untouched. User can `log` again later, or
   `cancel` to drop it.

## Step 5 — status

```bash
{python_cmd} {skill_dir}/scripts/worklog.py status [KEY]
```

Read-only. Print each tracked ticket: key, active/paused, elapsed so far, parent key,
note.

## Step 6 — cancel

```bash
{python_cmd} {skill_dir}/scripts/worklog.py discard <KEY>
```

Confirm before discarding — throws away tracked time, no Jira write, unrecoverable.

## Notes

- State lives in `~/.claude/jira-worklog/state.json` — per-user, outside this repo.
  Installer force-copies `skills/jira-worklog/` on every sync; state kept inside it
  would get wiped.
- Elapsed time = wall clock from `start` to `log`, minus paused spans. Includes any
  idle time inside an active (non-paused) stretch — no way to detect true idle vs
  active AI work without real session hooks. Pause/resume is the manual escape hatch.
- Never post worklog without explicit confirm (Step 4.5) — visible to whole team,
  wrong duration/comment cheap to avoid up front, expensive to explain after the fact.
- Multiple tickets can track concurrently, but only one should stay `active` at a
  time in practice — Step 3's auto-pause-on-switch keeps that true without extra
  user action.
- Duration rounds to nearest minute; under 1 minute never gets logged (Step 4.2).
- Token rollup (Step 4.3) sums Claude Code transcript usage (`~/.claude/projects/`)
  across every non-paused window for the key, minus cache-read tokens — spans
  session restarts, but not
  concurrent Claude Code windows on the same project open during the same window
  (those get counted too, no way to isolate one window's turns from another's).
  `pausedIntervals` (added alongside `pausedSeconds`) makes this window-exclusion
  exact across ticket switches, not just an approximation.
