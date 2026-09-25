#!/usr/bin/env python3
"""Sync test-cases/*.md into Test Tiger.

The markdown files are the source of truth; this pushes drafts into a Test Tiger
suite and records what landed. Talks to the API through test_tiger_client.py,
which lives beside this file - no external plugin, because this repo installs by
copying directories and has no way to declare such a dependency.

One pass per case. Metadata goes in at creation (description, label, mapped
priority), so nothing needs patching afterward.

Per case, independently:
  - title already in the suite -> update metadata (--mode auto-update, default)
                                  or leave alone (--mode auto-skip)
  - title is new                -> create it with its steps
  - either fails                -> that case stays `draft`; the rest still sync

Only cases the API confirmed get `status: uploaded` and a `tiger_id`. A re-run
therefore retries exactly the ones that did not land, and never double-creates
the ones that did.

Prerequisites:
  - TESTCASES_KEY set, or saved via `test_tiger_client.py setup --key ...`
  - a Test Tiger suite id (from component-map, or --suite-id)

Usage:
    sync_test_tiger.py --input test-cases/ --suite-id 1234 [--jira KEY]
                       [--mode auto-update|auto-skip] [--dry-run]
                       [--retire-superseded]
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_test_cases import (  # noqa: E402
    clear_supersedes,
    load_cases,
    select_drafts,
    set_frontmatter_field,
    set_status,
    validate,
)
from test_tiger_client import (  # noqa: E402
    UnauthorizedError,
    client,
    create_case,
    delete_case,
    find_or_create_suite,
    list_suite_cases,
    list_suites,
    update_case,
)

# Test Tiger's Priority enum accepts only HIGH / MEDIUM / LOW - posting
# CRITICAL fails with HTTP 400 "not one of the values accepted for Enum class".
# Matches test-case-rules.md, which maps "P0 / P1 - High".
PRIORITY = {"P0": "HIGH", "P1": "HIGH", "P2": "MEDIUM", "P3": "LOW"}

NUMBERED_STEP = re.compile(r"^\s*\d+[.)]\s+")


def split_steps(step_action, expected_result):
    """Turn the `## Steps` block into per-step records.

    The .md format keeps steps numbered in one block and `## Expected Result` as
    one line per scenario - not a per-step pairing. So each numbered step becomes
    its own action, and the whole expected block lands on the final step, which is
    the one that verifies the case. Pairing them positionally would assert the
    wrong thing on the wrong step.
    """
    actions = []
    for line in step_action.splitlines():
        stripped = line.strip()
        if NUMBERED_STEP.match(line):
            actions.append(NUMBERED_STEP.sub("", line).strip())
        elif not stripped:
            continue
        elif actions:
            actions[-1] += " " + stripped  # wrapped continuation line
        else:
            actions.append(stripped)  # unnumbered block, no step markers

    if not actions:
        actions = [step_action.strip() or " - "]

    steps = [{"action": a, "expected": ""} for a in actions]
    steps[-1]["expected"] = expected_result.strip()
    return steps


def to_payload(case):
    """Map one .md case -> the Test Tiger create payload."""
    return {
        "name": str(case["test_case"]).strip(),
        "description": str(case.get("test_summary") or "").strip(),
        "precondition": str(case.get("preconditions") or "").strip() or " - ",
        "priority": PRIORITY.get(str(case.get("importance", "")).strip(), "MEDIUM"),
        "label": str(case.get("jira") or "").strip(),
        "steps": split_steps(case.get("step_action", ""), case.get("expected_result", "")),
    }


def sync_one(api, suite_id, case, existing, mode):
    """Push one case. Returns (case_id, verb) or raises.

    verb is 'created' / 'updated' / 'skipped'.
    """
    payload = to_payload(case)
    match = existing.get(payload["name"].lower())

    if match:
        if mode == "auto-skip":
            return match["id"], "skipped"
        update_case(
            api, match["id"],
            description=payload["description"],
            precondition=payload["precondition"],
            priority=payload["priority"],
            label=payload["label"],
        )
        return match["id"], "updated"

    case_id, _ = create_case(
        api, suite_id,
        name=payload["name"],
        description=payload["description"],
        precondition=payload["precondition"],
        priority=payload["priority"],
        label=payload["label"],
        steps=payload["steps"],
    )
    return case_id, "created"


def retire_superseded(api, synced, by_name):
    """Delete the rows the newly synced cases replace, then their local files."""
    deleted, manual = [], []
    for case in synced:
        old_name = case.get("supersedes")
        if not old_name:
            continue
        old = by_name.get(old_name)
        if old is None:
            continue
        tiger_id = str(old.get("tiger_id") or "").strip()
        if not tiger_id:
            # Pre-sync case: delivered via the xlsx path, so no id was recorded.
            manual.append((old_name, None, "no tiger_id recorded - delete the row by hand"))
            continue
        try:
            delete_case(api, tiger_id)
        except (RuntimeError, UnauthorizedError) as exc:
            manual.append((old_name, tiger_id, str(exc)))
            continue
        old["_file"].unlink()
        clear_supersedes(case["_file"])
        deleted.append((old_name, tiger_id))
    return deleted, manual


def resolve_suite(api, args):
    """Return (suite_id, note). Find-or-create the release folder when named.

    --suite-id given → use it verbatim, no note.
    --suite-name given → find it under --parent-id, creating it if absent, so a
    new release does not need a manual folder in the Test Tiger UI first.
    """
    if args.suite_id:
        return args.suite_id, None
    suite_id, created = find_or_create_suite(
        api, args.suite_name, args.project_id, args.parent_id
    )
    note = (f"created folder {args.suite_name!r} → suite {suite_id}" if created
            else f"folder {args.suite_name!r} already exists → suite {suite_id}")
    return suite_id, note


def main():
    ap = argparse.ArgumentParser(description="Sync test-cases/*.md to Test Tiger")
    ap.add_argument("--input", required=True, help="Directory of test-case .md files")
    ap.add_argument("--suite-id", help="Target suite id. Omit to resolve by name via --suite-name.")
    ap.add_argument("--suite-name",
                    help="Resolve the target by name: find-or-create it under --parent-id. "
                         "Use for a release folder that may not exist yet.")
    ap.add_argument("--project-id", help="Project id. Required with --suite-name.")
    ap.add_argument("--parent-id",
                    help="Nest the --suite-name folder under this suite (e.g. a Release).")
    ap.add_argument("--jira", help="Only this ticket's cases")
    ap.add_argument("--mode", choices=["auto-update", "auto-skip"], default="auto-update",
                    help="On title match: update metadata (default) or leave it alone")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the payloads and the live-suite diff, write nothing")
    ap.add_argument("--retire-superseded", action="store_true",
                    help="After a clean sync, delete the Test Tiger rows this run supersedes "
                         "and their local files. Destructive - off by default.")
    args = ap.parse_args()

    if not args.suite_id and not (args.suite_name and args.project_id):
        sys.exit("ERROR: give --suite-id, or --suite-name with --project-id "
                 "(add --parent-id to nest under a Release).")

    input_dir = Path(args.input)
    if not input_dir.is_dir():
        sys.exit(f"ERROR: input directory not found: {input_dir}")

    cases, load_errors = load_cases(input_dir)
    errors = load_errors + (validate(cases) if cases else [])
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} problem(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    drafts = select_drafts(cases, args.jira)
    if not drafts:
        print(f"no draft cases to sync{f' for {args.jira}' if args.jira else ''}")
        return

    if args.dry_run:
        print(json.dumps([to_payload(c) for c in drafts], indent=2, ensure_ascii=False))
        target = f"suite {args.suite_id}" if args.suite_id else f"folder {args.suite_name!r}"
        print(f"\ndry-run: {len(drafts)} case(s) would sync to {target}")
        # Reach the API only to preview; a dry run must create nothing and must
        # still work before the key is set up.
        try:
            api = client()
        except (RuntimeError, UnauthorizedError, SystemExit):
            print("  (no API key yet - cannot preview the suite or the live diff)")
            return

        suite_id = args.suite_id
        if not suite_id:
            # Non-mutating existence check — never create during a dry run.
            match = next((s for s in list_suites(api, args.project_id)
                          if s["name"].lower() == args.suite_name.strip().lower()
                          and (not args.parent_id or str(s["parent_id"]) == str(args.parent_id))),
                         None)
            if match:
                suite_id = match["id"]
                print(f"  folder {args.suite_name!r} exists → suite {suite_id}")
            else:
                print(f"  folder {args.suite_name!r} does NOT exist → would be created on sync")
                return  # nothing to diff against yet

        existing = list_suite_cases(api, suite_id)
        for case in drafts:
            title = str(case["test_case"]).strip()
            hit = existing.get(title.lower())
            print(f"  {'~ update' if hit else '+ create'}  {title}"
                  + (f"  [{hit['id']}]" if hit else ""))
        return

    try:
        api = client()
        suite_id, suite_note = resolve_suite(api, args)
        if suite_note:
            print(suite_note)
        existing = list_suite_cases(api, suite_id)
    except UnauthorizedError as exc:
        sys.exit(f"ERROR: {exc}")
    except RuntimeError as exc:
        sys.exit(f"ERROR: cannot reach Test Tiger: {exc}")

    synced, unsynced = [], []
    for case in drafts:
        title = str(case["test_case"]).strip()
        try:
            case_id, verb = sync_one(api, suite_id, case, existing, args.mode)
        except (RuntimeError, UnauthorizedError) as exc:
            unsynced.append((title, str(exc).splitlines()[0]))
            continue

        if verb == "skipped":
            unsynced.append((title, f"duplicate of case {case_id} - left alone (--mode auto-skip)"))
            continue

        set_frontmatter_field(case["_file"], "tiger_id", case_id)
        set_status(case["_file"], "uploaded")
        synced.append(case)
        print(f"  {'+' if verb == 'created' else '~'} [{case_id}] {title}")

    print()
    print(f"synced={len(synced)} suite={suite_id} mode={args.mode}")
    if synced:
        print("  marked uploaded locally - the API confirmed each one")

    if args.retire_superseded and synced:
        by_name = {c["_name"]: c for c in cases}
        deleted, manual = retire_superseded(api, synced, by_name)
        if deleted:
            print(f"\nretired={len(deleted)} (Test Tiger row + local file deleted):")
            for name, tiger_id in deleted:
                print(f"  x [{tiger_id}] {name}")
        if manual:
            print(f"\nDELETE BY HAND ({len(manual)}) - these superseded rows are still live:")
            for name, tiger_id, why in manual:
                print(f"  ! {name} ({tiger_id or 'no id'}): {why}")
    elif synced and any(c.get("supersedes") for c in synced):
        pending = [c["_name"] for c in synced if c.get("supersedes")]
        print(f"\n{len(pending)} synced case(s) supersede an older one, still live in Test Tiger.")
        print("  re-run with --retire-superseded to delete those rows and their local files.")

    if unsynced:
        print(f"\nNOT synced ({len(unsynced)}) - left as draft, safe to re-run:", file=sys.stderr)
        for title, why in unsynced:
            print(f"  - {title}: {why}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
