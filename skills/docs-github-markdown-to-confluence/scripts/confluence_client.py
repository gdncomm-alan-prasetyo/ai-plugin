"""Minimal Confluence Cloud client for the docs-github-markdown-to-confluence skill.

Two host/version facts, both learned the hard way:

1. Scoped API tokens (the ``ATATT...`` kind created with an explicit scope list) only work
   against the ``api.atlassian.com/ex/confluence/<cloudId>/wiki`` gateway. The
   ``<site>.atlassian.net`` host returns 401 for them.
2. v1 and v2 endpoints require *different* granular scopes. v2 page access wants
   ``read:page:confluence`` / ``write:page:confluence``; v1 wants
   ``read:content-details:confluence`` and friends. A token scoped only for v2 therefore
   gets 401 from every v1 endpoint -- which looks like "v1 rejects scoped tokens" but is
   really just a missing scope.

Attachment creation exists on v1 only, and needs BOTH
``write:attachment:confluence`` and ``read:content-details:confluence``.
:meth:`ConfluenceClient.upload_attachment` reports failure rather than raising, so a
token lacking those degrades to source-only Mermaid instead of aborting the sync.

Environment:
    CONFLUENCE_EMAIL      Atlassian account email (basic-auth username)
    CONFLUENCE_API_TOKEN  API token (basic-auth password)
    CONFLUENCE_API_BASE   e.g. https://api.atlassian.com/ex/confluence/<cloudId>/wiki
    CONFLUENCE_CLOUD_ID   used to build API_BASE when it is not set directly
    CONFLUENCE_SITE_URL   e.g. https://gdncomm.atlassian.net, used only to build
                          human-facing page links
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests

TIMEOUT = 60
SYNC_PROPERTY_KEY = "githubMarkdownSync"


class ConfluenceError(RuntimeError):
    """An API call failed. Carries the status code so callers can branch on it."""

    def __init__(self, status: int, method: str, url: str, body: str):
        self.status = status
        self.method = method
        self.url = url
        self.body = body
        super().__init__("{} {} -> {}\n{}".format(method, url, status, body[:800]))


class ConfluenceClient:
    def __init__(self, base: Optional[str] = None, email: Optional[str] = None,
                 token: Optional[str] = None, site_url: Optional[str] = None):
        self.email = email or os.environ.get("CONFLUENCE_EMAIL", "")
        self.token = token or os.environ.get("CONFLUENCE_API_TOKEN", "")
        self.site_url = (site_url or os.environ.get("CONFLUENCE_SITE_URL", "")).rstrip("/")

        self.base = (base or os.environ.get("CONFLUENCE_API_BASE", "")).rstrip("/")
        if not self.base:
            cloud_id = os.environ.get("CONFLUENCE_CLOUD_ID", "")
            if cloud_id:
                self.base = ("https://api.atlassian.com/ex/confluence/"
                             "{}/wiki".format(cloud_id))

        missing = [n for n, v in (("CONFLUENCE_EMAIL", self.email),
                                  ("CONFLUENCE_API_TOKEN", self.token),
                                  ("CONFLUENCE_API_BASE or CONFLUENCE_CLOUD_ID", self.base))
                   if not v]
        if missing:
            raise SystemExit("Missing required environment: " + ", ".join(missing))

        self.session = requests.Session()
        self.session.auth = (self.email, self.token)
        self.session.headers.update({"Accept": "application/json"})

    # ---------------------------------------------------------------- plumbing

    def _req(self, method: str, path: str, **kw) -> Any:
        url = path if path.startswith("http") else self.base + path
        resp = self.session.request(method, url, timeout=TIMEOUT, **kw)
        if not resp.ok:
            raise ConfluenceError(resp.status_code, method, url, resp.text or "")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def _paged(self, path: str, params: Optional[Dict] = None) -> List[Dict]:
        """Follow v2 cursor pagination to exhaustion."""
        out: List[Dict] = []
        params = dict(params or {})
        params.setdefault("limit", 100)
        next_path: Optional[str] = path
        while next_path:
            data = self._req("GET", next_path, params=params if next_path == path else None)
            out.extend(data.get("results", []))
            link = (data.get("_links") or {}).get("next")
            # v2 returns next as "/wiki/api/v2/...", already including the /wiki prefix
            next_path = None
            if link:
                base_root = self.base[: -len("/wiki")] if self.base.endswith("/wiki") else self.base
                next_path = base_root + link
        return out

    # ------------------------------------------------------------------ pages

    def get_page(self, page_id: str, body_format: str = "storage") -> Dict:
        return self._req("GET", "/api/v2/pages/{}".format(page_id),
                         params={"body-format": body_format})

    def get_child_pages(self, page_id: str) -> List[Dict]:
        return self._paged("/api/v2/pages/{}/children".format(page_id))

    def create_page(self, space_id: str, parent_id: Optional[str], title: str,
                    storage_body: str) -> Dict:
        payload: Dict[str, Any] = {
            "spaceId": str(space_id),
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": storage_body},
        }
        if parent_id:
            payload["parentId"] = str(parent_id)
        return self._req("POST", "/api/v2/pages", json=payload)

    def update_page(self, page_id: str, title: str, storage_body: str,
                    version_number: int, message: str = "") -> Dict:
        payload = {
            "id": str(page_id),
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": storage_body},
            "version": {"number": int(version_number) + 1, "message": message},
        }
        return self._req("PUT", "/api/v2/pages/{}".format(page_id), json=payload)

    def rename_page(self, page_id: str, new_title: str) -> Dict:
        """Change a page's title, leaving its body untouched.

        v2's PUT requires the full representation, so the current body has to be read and
        sent straight back -- omitting it would blank the page.
        """
        page = self.get_page(page_id, body_format="storage")
        body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
        version = (page.get("version") or {}).get("number", 1)
        return self.update_page(page_id, new_title, body, int(version),
                                message="Renamed by docs-github-markdown-to-confluence")

    # ------------------------------------------------------- content property

    def get_property(self, page_id: str, key: str = SYNC_PROPERTY_KEY) -> Optional[Dict]:
        """Return the raw property object (has ``value`` and ``version``), or None."""
        for prop in self._paged("/api/v2/pages/{}/properties".format(page_id)):
            if prop.get("key") == key:
                return prop
        return None

    def set_property(self, page_id: str, value: Dict,
                     key: str = SYNC_PROPERTY_KEY) -> Dict:
        """Create the property, or update it in place when it already exists."""
        existing = self.get_property(page_id, key)
        if existing is None:
            return self._req("POST", "/api/v2/pages/{}/properties".format(page_id),
                             json={"key": key, "value": value})
        version = ((existing.get("version") or {}).get("number") or 1)
        return self._req(
            "PUT",
            "/api/v2/pages/{}/properties/{}".format(page_id, existing["id"]),
            json={"key": key, "value": value, "version": {"number": int(version) + 1}},
        )

    # -------------------------------------------------------------- attachment

    def list_attachments(self, page_id: str) -> Dict[str, str]:
        """Map filename -> attachment id for a page.

        Deliberately the **v1** endpoint. The v2 equivalent
        (``GET /api/v2/pages/{id}/attachments``) needs ``read:attachment:confluence``,
        a fifth scope, whereas v1 is covered by ``read:content-details:confluence`` --
        which the token must already carry for the upload itself. Same data, one fewer
        scope to grant.
        """
        out: Dict[str, str] = {}
        start = 0
        try:
            while True:
                data = self._req(
                    "GET", "/rest/api/content/{}/child/attachment".format(page_id),
                    params={"limit": 100, "start": start})
                results = data.get("results", []) or []
                for att in results:
                    title = att.get("title")
                    if title:
                        out[title] = str(att.get("id"))
                if len(results) < data.get("limit", 100):
                    break
                start += len(results)
        except ConfluenceError:
            # Not fatal: without this the upsert simply re-uploads, costing an attachment
            # version rather than correctness.
            pass
        return out

    def upload_attachment(self, page_id: str, filename: str, data: bytes,
                          content_type: str = "image/png") -> Tuple[bool, str]:
        """Create *or replace* an attachment, by filename.

        Uses ``PUT /child/attachment``, which upserts: Confluence matches on filename and
        adds a new version when one already exists. The sibling ``POST`` on the same path
        only ever *adds*, so re-syncing a changed diagram through it would pile up
        duplicates rather than replace -- which is why PUT is the right verb here even
        though creating is the common case.

        Returns ``(ok, detail)`` rather than raising: this is a v1 endpoint needing scopes
        a v2-only token will not have, so failure is an expected outcome that callers
        handle by falling back to a code block.
        """
        url = "{}/rest/api/content/{}/child/attachment".format(self.base, page_id)
        try:
            resp = self.session.put(
                url,
                headers={"X-Atlassian-Token": "no-check"},
                files={"file": (filename, data, content_type)},
                data={"minorEdit": "true",
                      "comment": "Rendered by docs-github-markdown-to-confluence"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:  # network-level
            return False, "request failed: {}".format(exc)

        if resp.ok:
            return True, "upserted"
        if resp.status_code in (401, 403):
            return False, (
                "HTTP {} -- attachment upload is a v1 endpoint and needs BOTH "
                "'write:attachment:confluence' and 'read:content-details:confluence' on "
                "the token. A token scoped only for v2 page access will not have the "
                "second one.".format(resp.status_code)
            )
        return False, "HTTP {}: {}".format(resp.status_code, (resp.text or "")[:300])

    # ------------------------------------------------------------------ helper

    def page_web_url(self, page: Dict) -> str:
        """Best-effort human-facing URL for a page object."""
        links = page.get("_links") or {}
        webui = links.get("webui") or ""
        base = self.site_url or links.get("base") or ""
        if webui and base:
            return "{}/wiki{}".format(base.rstrip("/"), webui) if "/wiki" not in base else base.rstrip("/") + webui
        return "{}/wiki/spaces/~/pages/{}".format(self.site_url, page.get("id"))


def parse_page_id(page_ref: str) -> str:
    """Accept a bare id or any Confluence page URL and return the numeric page id."""
    page_ref = page_ref.strip()
    if page_ref.isdigit():
        return page_ref
    m = re.search(r"/pages/(?:edit-v2/)?(\d+)", page_ref)
    if m:
        return m.group(1)
    m = re.search(r"[?&]pageId=(\d+)", page_ref)
    if m:
        return m.group(1)
    raise SystemExit("Could not find a page id in: {}".format(page_ref))


def main(argv: List[str]) -> int:
    """Tiny self-check: verify credentials and report what the token can actually do."""
    client = ConfluenceClient()
    page_id = parse_page_id(argv[0]) if argv else None
    print("API base: {}".format(client.base))
    if page_id:
        page = client.get_page(page_id)
        print("page {}: {!r} (version {}, spaceId {})".format(
            page_id, page.get("title"), (page.get("version") or {}).get("number"),
            page.get("spaceId")))
        prop = client.get_property(page_id)
        print("sync property: {}".format(json.dumps(prop.get("value")) if prop else "(none)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
