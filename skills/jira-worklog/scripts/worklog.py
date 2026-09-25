#!/usr/bin/env python3
"""Jira worklog time-tracking CLI. No deps beyond stdlib + jira-issues' jira_client.py.

State file: ~/.claude/jira-worklog/state.json — one entry per subtask key being tracked.
Output: line-delimited key=value (same convention as jira-issues CLI).
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone


STATE_PATH = os.path.expanduser('~/.claude/jira-worklog/state.json')


def load_client(jira_client_path):
    spec = importlib.util.spec_from_file_location('jira_client', jira_client_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_client()


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def now_iso():
    return datetime.now().astimezone().isoformat()


def parse_iso(s):
    return datetime.fromisoformat(s)


def jira_started(dt):
    """Format for Jira's worklog `started` field: yyyy-MM-dd'T'HH:mm:ss.SSSZ (no colon in offset)."""
    s = dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
    offset = dt.strftime('%z') or '+0000'
    return f'{s}{offset}'


def format_duration(total_seconds):
    minutes = round(total_seconds / 60)
    if minutes <= 0:
        return None
    if minutes < 60:
        return f'{minutes}m'
    h, m = divmod(minutes, 60)
    return f'{h}h {m}m' if m else f'{h}h'


def elapsed_seconds(entry):
    started = parse_iso(entry['startedAt'])
    now = datetime.now().astimezone()
    paused = entry.get('pausedSeconds', 0)
    if entry.get('status') == 'paused' and entry.get('pausedAt'):
        now = parse_iso(entry['pausedAt'])
    return (now - started).total_seconds() - paused


def parse_iso_utc(s):
    """Parse either a state-file local-offset ISO string or a transcript UTC 'Z' string."""
    if s.endswith('Z'):
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    else:
        dt = parse_iso(s)
    return dt.astimezone(timezone.utc)


def active_windows(entry):
    """Non-paused (start, end) UTC windows, derived from pausedIntervals."""
    windows = []
    cursor = parse_iso_utc(entry['startedAt'])
    for interval in entry.get('pausedIntervals', []):
        windows.append((cursor, parse_iso_utc(interval['start'])))
        if interval.get('end') is None:
            return windows
        cursor = parse_iso_utc(interval['end'])
    if entry.get('status') == 'paused' and entry.get('pausedAt'):
        end = parse_iso_utc(entry['pausedAt'])
    else:
        end = datetime.now(timezone.utc)
    windows.append((cursor, end))
    return windows


def transcript_dir():
    sanitized = os.getcwd().replace(':', '-').replace('\\', '-').replace('/', '-').replace('.', '-')
    return os.path.expanduser(f'~/.claude/projects/{sanitized}')


def sum_tokens(windows):
    totals = {
        'output_tokens': 0,
        'input_tokens': 0,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0,
    }
    tdir = transcript_dir()
    if not os.path.isdir(tdir):
        return totals
    for fname in os.listdir(tdir):
        if not fname.endswith('.jsonl'):
            continue
        try:
            with open(os.path.join(tdir, fname), 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get('type') != 'assistant':
                        continue
                    msg = obj.get('message')
                    ts = obj.get('timestamp')
                    if not isinstance(msg, dict) or 'usage' not in msg or not ts:
                        continue
                    msg_time = parse_iso_utc(ts)
                    if not any(start <= msg_time < end for start, end in windows):
                        continue
                    usage = msg['usage']
                    for k in totals:
                        totals[k] += usage.get(k, 0) or 0
        except OSError:
            continue
    return totals


def cmd_resolve(args):
    client = load_client(args.jira_client)
    issue = client.get(f'issue/{args.key}', params={
        'fields': 'summary,status,issuetype,parent,subtasks',
    })
    fields = issue.get('fields', {})
    issuetype = fields.get('issuetype', {}) or {}
    is_subtask = bool(issuetype.get('subtask'))
    print('success=true')
    print(f'key={issue.get("key", args.key)}')
    print(f'summary={fields.get("summary", "")}')
    print(f'issuetype={issuetype.get("name", "")}')
    print(f'is_subtask={"true" if is_subtask else "false"}')

    if is_subtask:
        parent = fields.get('parent', {}) or {}
        print(f'parent_key={parent.get("key", "")}')
        print(f'auto_target={issue.get("key", args.key)}')
        return

    subtasks = fields.get('subtasks', []) or []
    print(f'parent_key={issue.get("key", args.key)}')
    print(f'subtask_count={len(subtasks)}')
    for st in subtasks:
        st_fields = st.get('fields', {}) or {}
        summary = st_fields.get('summary', '')
        status = (st_fields.get('status', {}) or {}).get('name', '')
        print(f'subtask={st.get("key", "")}|{summary}|{status}')

    auto_target = subtasks[0].get('key', '') if len(subtasks) == 1 else ''
    print(f'auto_target={auto_target}')


def cmd_start(args):
    state = load_state()
    existing = state.get(args.key)
    if existing and existing.get('status') in ('active', 'paused'):
        print('success=true')
        print('already_tracking=true')
        print(f'key={args.key}')
        print(f'status={existing["status"]}')
        print(f'elapsed_seconds={int(elapsed_seconds(existing))}')
        return
    state[args.key] = {
        'parentKey': args.parent or args.key,
        'resolvedFromKey': args.from_key or args.key,
        'status': 'active',
        'startedAt': now_iso(),
        'pausedAt': None,
        'pausedSeconds': 0,
        'pausedIntervals': [],
        'note': args.note or '',
        'repo': os.getcwd(),
    }
    save_state(state)
    print('success=true')
    print('already_tracking=false')
    print(f'key={args.key}')
    print(f'started_at={state[args.key]["startedAt"]}')


def cmd_status(args):
    state = load_state()
    keys = [args.key] if args.key else list(state.keys())
    print(f'count={len(keys)}')
    for k in keys:
        entry = state.get(k)
        if not entry:
            print(f'entry={k}|not_tracked|||')
            continue
        secs = int(elapsed_seconds(entry))
        dur = format_duration(secs) or '0m'
        print(f'entry={k}|{entry["status"]}|{dur}|{entry.get("parentKey","")}|{entry.get("note","")}')


def cmd_pause(args):
    state = load_state()
    entry = state.get(args.key)
    if not entry:
        print('success=false')
        print('error=not_tracked')
        sys.exit(1)
    if entry['status'] == 'paused':
        print('success=true')
        print('already_paused=true')
        return
    entry['status'] = 'paused'
    entry['pausedAt'] = now_iso()
    entry.setdefault('pausedIntervals', []).append({'start': entry['pausedAt'], 'end': None})
    save_state(state)
    print('success=true')
    print(f'key={args.key}')
    print('status=paused')


def cmd_resume(args):
    state = load_state()
    entry = state.get(args.key)
    if not entry:
        print('success=false')
        print('error=not_tracked')
        sys.exit(1)
    if entry['status'] == 'active':
        print('success=true')
        print('already_active=true')
        return
    paused_at = parse_iso(entry['pausedAt'])
    now = datetime.now().astimezone()
    entry['pausedSeconds'] = entry.get('pausedSeconds', 0) + (now - paused_at).total_seconds()
    resumed_at = now_iso()
    intervals = entry.setdefault('pausedIntervals', [])
    if intervals and intervals[-1].get('end') is None:
        intervals[-1]['end'] = resumed_at
    entry['pausedAt'] = None
    entry['status'] = 'active'
    save_state(state)
    print('success=true')
    print(f'key={args.key}')
    print('status=active')


def cmd_compute(args):
    state = load_state()
    entry = state.get(args.key)
    if not entry:
        print('success=false')
        print('error=not_tracked')
        sys.exit(1)
    secs = elapsed_seconds(entry)
    dur = format_duration(secs)
    print('success=true')
    print(f'key={args.key}')
    print(f'elapsed_seconds={int(secs)}')
    print(f'time_spent={dur or ""}')
    print(f'too_short={"true" if dur is None else "false"}')
    print(f'started_at={entry["startedAt"]}')
    print(f'parent_key={entry.get("parentKey","")}')
    print(f'note={entry.get("note","")}')


def cmd_tokens(args):
    state = load_state()
    entry = state.get(args.key)
    if not entry:
        print('success=false')
        print('error=not_tracked')
        sys.exit(1)
    totals = sum_tokens(active_windows(entry))
    actual_tokens = (
        totals['output_tokens']
        + totals['input_tokens']
        + totals['cache_creation_input_tokens']
    )
    print('success=true')
    print(f'key={args.key}')
    print(f'actual_tokens={actual_tokens}')
    print(f'output_tokens={totals["output_tokens"]}')
    print(f'input_tokens={totals["input_tokens"]}')
    print(f'cache_creation_tokens={totals["cache_creation_input_tokens"]}')
    print(f'cache_read_tokens_excluded={totals["cache_read_input_tokens"]}')


def cmd_discard(args):
    state = load_state()
    if args.key in state:
        del state[args.key]
        save_state(state)
        print('success=true')
        print('discarded=true')
    else:
        print('success=true')
        print('discarded=false')


def cmd_post(args):
    state = load_state()
    entry = state.get(args.key)
    if not entry:
        print('success=false')
        print('error=not_tracked')
        sys.exit(1)

    client = load_client(args.jira_client)
    started_dt = parse_iso(entry['startedAt'])
    payload = {
        'timeSpent': args.time_spent,
        'started': jira_started(started_dt),
    }
    if args.comment:
        payload['comment'] = {
            'type': 'doc',
            'version': 1,
            'content': [
                {'type': 'paragraph', 'content': [{'type': 'text', 'text': args.comment}]}
            ],
        }
    result = client.post(f'issue/{args.key}/worklog', data=payload)
    del state[args.key]
    save_state(state)
    print('success=true')
    print(f'key={args.key}')
    print(f'worklog_id={result.get("id", "")}')
    print(f'time_spent={args.time_spent}')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)

    p_resolve = sub.add_parser('resolve')
    p_resolve.add_argument('key')
    p_resolve.add_argument('--jira-client', required=True)

    p_start = sub.add_parser('start')
    p_start.add_argument('key')
    p_start.add_argument('--parent')
    p_start.add_argument('--from-key', dest='from_key')
    p_start.add_argument('--note', default='')

    p_status = sub.add_parser('status')
    p_status.add_argument('key', nargs='?')

    p_pause = sub.add_parser('pause')
    p_pause.add_argument('key')

    p_resume = sub.add_parser('resume')
    p_resume.add_argument('key')

    p_compute = sub.add_parser('compute')
    p_compute.add_argument('key')

    p_tokens = sub.add_parser('tokens')
    p_tokens.add_argument('key')

    p_discard = sub.add_parser('discard')
    p_discard.add_argument('key')

    p_post = sub.add_parser('post')
    p_post.add_argument('key')
    p_post.add_argument('--jira-client', required=True)
    p_post.add_argument('--time-spent', required=True)
    p_post.add_argument('--comment', default='')

    args = parser.parse_args()
    {
        'resolve': cmd_resolve,
        'start': cmd_start,
        'status': cmd_status,
        'pause': cmd_pause,
        'resume': cmd_resume,
        'compute': cmd_compute,
        'tokens': cmd_tokens,
        'discard': cmd_discard,
        'post': cmd_post,
    }[args.command](args)


if __name__ == '__main__':
    main()
