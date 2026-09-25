#!/usr/bin/env python3
"""Minimal Test Tiger (Test Intelligent Manager) REST client.

Self-contained on purpose. This repo installs by copying directories - it has no
manifest that can declare a dependency on another team's plugin - so a sync path
that shells out to one silently does nothing on a machine where that plugin was
never installed. Owning ~5 endpoints beats a dependency we cannot express.

Surface deliberately narrow. Everything needed to push test-cases/*.md and to
discover a suite id, nothing else:

    GET    /api/project                      projects (discovery)
    GET    /api/testSuite/project/{id}       suite tree (discovery)
    GET    /api/testCase/testSuite?id=       cases in a suite (dedup)
    POST   /api/testCase                     create case
    POST   /api/testStep                     add one step to a case
    PUT    /api/testCase/{id}                update case metadata
    DELETE /api/testCase/{id}                delete case (retire/supersede)

Auth is one header. The key is personal - read from TESTCASES_KEY, else from
the saved config. Never logged, never echoed; `setup` masks it on the way in.

Usage (discovery, so you can fill component-map without the plugin):
    test_tiger_client.py setup --key <key>
    test_tiger_client.py projects [--search iam]
    test_tiger_client.py suites <project-id>
    test_tiger_client.py cases-by-suite <suite-id>
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://test-tiger.gdn-app.com"
KEY_ENV = "TESTCASES_KEY"
KEY_URL = "https://test-tiger.gdn-app.com/account/detail"

# Not under the skill directory: install.sh overwrites that with `cp -r`, which
# would wipe a saved key on every update.
CONFIG_FILE = Path.home() / ".claude" / ".testcase-tiger.json"

VALID_PRIORITY = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


class UnauthorizedError(RuntimeError):
    """API returned HTTP 401."""


def ssl_context():
    """Prefer certifi when present - stock macOS python3 often ships no CA bundle."""
    if os.environ.get("SSL_CERT_FILE"):
        return None  # honour the caller's explicit bundle
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


class APIClient:
    def __init__(self, key, base_url=BASE_URL):
        self.base = base_url.rstrip("/")
        self.ctx = ssl_context()
        self.headers = {
            "x-api-dev-key": key,
            # Keep the QA team's telemetry tag: their dashboards split
            # agent-driven writes from human ones.
            "x-api-source": "ai-assistant",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method, path, params=None, body=None):
        url = self.base + path
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None and str(v) != ""}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30, context=self.ctx) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            if e.code == 401:
                raise UnauthorizedError(
                    f"Unauthorized (HTTP 401). {KEY_ENV} may be invalid or expired.\n"
                    f"  Generate a new key at: {KEY_URL}"
                ) from e
            raise RuntimeError(f"HTTP {e.code} on {method} {path}: {detail}") from e
        except urllib.error.URLError as e:
            hint = ""
            if "CERTIFICATE_VERIFY" in str(e.reason):
                hint = ("\n  TLS trust store missing. Fix with:\n"
                        "    python3 -m pip install --user certifi")
            raise RuntimeError(f"Connection failed: {e.reason}{hint}") from e

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, body):
        return self._request("POST", path, body=body)

    def put(self, path, body):
        return self._request("PUT", path, body=body)

    def delete(self, path):
        return self._request("DELETE", path)


def items_of(response):
    """Unwrap the API's {data: [...]} / {data: {content: [...]}} envelopes."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        data = response.get("data", response)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("content", [])
    return []


def data_of(response):
    return response.get("data", response) if isinstance(response, dict) else response


# --- key handling -----------------------------------------------------------

def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    except (OSError, ValueError):
        return {}


def save_key(key):
    key = key.strip()
    if not key:
        sys.exit("ERROR: --key is empty")
    cfg = load_config()
    cfg["api_key"] = key
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    CONFIG_FILE.chmod(0o600)  # personal credential
    masked = key[:4] + "*" * max(len(key) - 8, 4) + key[-4:] if len(key) > 8 else "****"
    print(f"key_saved={masked}")
    print(f"config={CONFIG_FILE}")


def get_key():
    key = os.environ.get(KEY_ENV, "").strip() or load_config().get("api_key", "").strip()
    if not key:
        print("key_missing=true", file=sys.stderr)
        print(f"  set {KEY_ENV}, or run: test_tiger_client.py setup --key <key>", file=sys.stderr)
        print(f"  generate one at: {KEY_URL}", file=sys.stderr)
        sys.exit(2)
    return key


def client():
    return APIClient(get_key())


# --- operations used by sync_test_tiger.py ----------------------------------

def list_suite_cases(api, suite_id):
    """Existing cases in a suite, keyed by lowercased title (the dedup key)."""
    existing = {}
    for case in items_of(api.get("/api/testCase/testSuite", {"id": suite_id})):
        name = (case.get("name") or "").strip()
        if name:
            existing[name.lower()] = {"id": case.get("id"), "name": name}
    return existing


def create_case(api, suite_id, name, description="", precondition="",
                priority="MEDIUM", label="", steps=None):
    """Create a case, then its steps. Returns (case_id, steps_created).

    Full metadata goes in on creation - description, label and a true CRITICAL
    priority - so no second update call is needed to repair a lossy payload.
    """
    body = {"name": name, "testSuiteId": int(suite_id), "priority": priority}
    if description:
        body["description"] = description
    if precondition:
        body["preCondition"] = precondition
    if label:
        body["label"] = label

    case_id = data_of(api.post("/api/testCase", body)).get("id")
    if case_id is None:
        raise RuntimeError(f"create returned no id for {name!r}")

    made = 0
    for number, step in enumerate(steps or [], start=1):
        step_body = {
            "testCaseId": case_id,
            "stepNumber": number,
            "action": step.get("action", ""),
        }
        if step.get("expected"):
            step_body["expected"] = step["expected"]
        api.post("/api/testStep", step_body)
        made += 1
    return case_id, made


def update_case(api, case_id, name="", description="", precondition="",
                priority="", label=""):
    """Patch metadata. Reads current first so blank args never blank a field."""
    current = data_of(api.get(f"/api/testCase/{case_id}")) or {}
    body = {
        "name": name or current.get("name", ""),
        "description": description or current.get("description") or "",
        "preCondition": precondition or current.get("preCondition") or "",
        "priority": priority or current.get("priority") or "MEDIUM",
        "label": label or current.get("label") or "",
        "testSuiteId": current.get("testSuiteId"),
    }
    return data_of(api.put(f"/api/testCase/{case_id}", body)).get("id", case_id)


def delete_case(api, case_id):
    api.delete(f"/api/testCase/{case_id}")
    return case_id


def list_suites(api, project_id):
    """Flat list of every suite in a project: [{id, name, parent_id}].

    The API returns a tree; parent is derived from structure, not from a field
    name, so it holds whether the API calls the parent `parentId` or
    `testSuiteId`.
    """
    flat = []

    def walk(node, parent_id):
        flat.append({
            "id": node.get("id"),
            "name": (node.get("name") or "").strip(),
            "parent_id": parent_id,
        })
        for child in node.get("children") or node.get("testSuites") or []:
            walk(child, node.get("id"))

    for root in items_of(api.get(f"/api/testSuite/project/{project_id}")):
        walk(root, None)
    return flat


def create_suite(api, name, project_id, parent_id=None, description=""):
    """Create one suite. Returns its id. Not idempotent — see find_or_create_suite."""
    body = {"name": name, "projectId": int(project_id)}
    if parent_id:
        body["parentId"] = int(parent_id)
    if description:
        body["description"] = description
    suite_id = data_of(api.post("/api/testSuite", body)).get("id")
    if suite_id is None:
        raise RuntimeError(f"create suite returned no id for {name!r}")
    return suite_id


def find_or_create_suite(api, name, project_id, parent_id=None):
    """Resolve a suite by exact name under parent_id, creating it if absent.

    Returns (suite_id, created). Idempotent — the same call twice yields the
    same id and creates nothing the second time. Match is case-insensitive on
    name and scoped to parent_id, so `Deployment_iam_27Jul2026` under one
    release never collides with the same name under another.
    """
    want = name.strip().lower()
    for s in list_suites(api, project_id):
        if s["name"].lower() == want and (
            parent_id is None or str(s["parent_id"]) == str(parent_id)
        ):
            return s["id"], False
    return create_suite(api, name, project_id, parent_id), True


# --- discovery CLI ----------------------------------------------------------

def cmd_projects(args):
    api = client()
    params = {"page": 0, "size": 50, "sortBy": "name", "sortDir": "ASC"}
    if args.search:
        params["projectName"] = args.search
    found = items_of(api.get("/api/project", params))
    print(f"count={len(found)}")
    for p in found:
        print(f"project={p.get('id')}|{p.get('name')}")


def print_suite(suite, depth):
    print(f"suite={suite.get('id')}|{'  ' * depth}{suite.get('name')}")
    for child in suite.get("children") or suite.get("testSuites") or []:
        print_suite(child, depth + 1)


def cmd_suites(args):
    for suite in items_of(client().get(f"/api/testSuite/project/{args.project_id}")):
        print_suite(suite, 0)


def cmd_cases_by_suite(args):
    existing = list_suite_cases(client(), args.suite_id)
    print(f"count={len(existing)}")
    for entry in existing.values():
        print(f"case={entry['id']}|{entry['name']}")


def cmd_create_suite(args):
    suite_id, created = find_or_create_suite(
        client(), args.name, args.project_id, args.parent_id
    )
    print(f"suite={suite_id}|{args.name}")
    print("created=true" if created else "created=false (already existed)")


def main():
    ap = argparse.ArgumentParser(description="Minimal Test Tiger client")
    sub = ap.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Save the API key (masked, chmod 600)")
    setup.add_argument("--key", required=True)

    sub.add_parser("setup-clear", help="Forget the saved API key")

    projects = sub.add_parser("projects", help="List projects")
    projects.add_argument("--search", default="")

    suites = sub.add_parser("suites", help="Suite tree for a project")
    suites.add_argument("project_id")

    cases = sub.add_parser("cases-by-suite", help="Cases in a suite")
    cases.add_argument("suite_id")

    mksuite = sub.add_parser("create-suite",
                             help="Find-or-create a suite (idempotent); prints its id")
    mksuite.add_argument("--project-id", required=True)
    mksuite.add_argument("--name", required=True)
    mksuite.add_argument("--parent-id", help="Nest under this suite (e.g. a Release)")

    args = ap.parse_args()
    try:
        if args.command == "setup":
            save_key(args.key)
        elif args.command == "setup-clear":
            cfg = load_config()
            cfg.pop("api_key", None)
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
            print("key_cleared=true")
        elif args.command == "projects":
            cmd_projects(args)
        elif args.command == "suites":
            cmd_suites(args)
        elif args.command == "cases-by-suite":
            cmd_cases_by_suite(args)
        elif args.command == "create-suite":
            cmd_create_suite(args)
    except UnauthorizedError as exc:
        sys.exit(f"ERROR: {exc}")
    except RuntimeError as exc:
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
