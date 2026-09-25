"""Publish GitHub markdown to Confluence, idempotently.

See SKILL.md for the contract. There are two modes:

**Folder mode** (``--folder``) publishes a page tree:

* the parent page you pass in receives that folder's ``README.md`` as its body, and gains
  a generated page-structure index at the bottom. **If the folder has no README.md the
  parent page is left completely alone** -- children are still published beneath it;
* every other ``.md`` file becomes a child page titled ``{parent-title} - {basename}``;
* a page whose source markdown has been deleted is renamed with a ``[DEPRECATED] - ``
  prefix, never removed.

**Single-file mode** (``--file``) publishes exactly one markdown file as the body of the
parent page. No children are created, no structure index is generated, and the
deprecation pass does not run -- a lone file makes no claim about what else belongs
under that page, so nothing else is touched.

Both modes:

* store a checksum of the source in a Confluence content property, so an unchanged file
  is skipped;
* inject a managed block containing the Confluence link into the markdown, written to the
  working tree only -- this script never commits.

Backlinks always point at ``--branch`` (default ``master``) and existence is not verified.
A ref inside a ``--folder`` URL locates the folder and is ignored for links, because a
feature branch disappears when its PR merges.

Two behaviours exist to stop it destroying things:

* the checksum is taken with the managed block *stripped*. Without that, injecting the
  link would change the file, which would look like a change on the next run, forever.
* the parent page is not overwritten on a first run unless ``--force-parent`` is passed,
  because README.md replaces its body and the target may be a hand-written page.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import md_to_storage as m2s  # noqa: E402
from confluence_client import (  # noqa: E402
    ConfluenceClient, ConfluenceError, parse_page_id,
)

DEPRECATED_PREFIX = "[DEPRECATED] - "
BLOCK_START = "<!-- confluence-sync:start -->"
BLOCK_END = "<!-- confluence-sync:end -->"
BLOCK_RE = re.compile(
    re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)

SKIP_DIRS = {".git", "node_modules", "target", "build", ".idea", "__pycache__"}


# --------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print("WARN: {}".format(msg), file=sys.stderr, flush=True)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_managed_block(md: str) -> str:
    """Remove the managed block and normalise, so the hash covers author content only.

    Collapsing blank runs is load-bearing, not tidiness. Injecting the block leaves the
    surrounding blank lines behind when it is removed again, so a file that originally read
    ``heading\\n\\ntext`` strips back to ``heading\\n\\n\\ntext`` -- one extra blank line,
    a different hash, and every page republishing on every run. Normalising both sides to
    the same shape is what actually makes the skip work.
    """
    cleaned = BLOCK_RE.sub("", md)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    # Exactly one blank line after a heading. Injection puts a blank line there whether or
    # not the author did, and collapsing runs cannot turn two newlines back into one, so
    # both sides have to be normalised to the same convention. Markdown renders a heading
    # followed directly by text identically, so nothing is lost.
    cleaned = re.sub(r"(?m)^(#{1,6} .*)\n(?!\n)", r"\1\n\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def run(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError("{} failed ({}): {}".format(
            " ".join(cmd), proc.returncode, (proc.stderr or proc.stdout).strip()[:500]))
    return proc.stdout.strip()


def first_h1(md: str) -> Optional[str]:
    for line in md.split("\n"):
        m = re.match(r"^#\s+(.*?)\s*#*$", line)
        if m:
            # Strip inline code backticks so labels read cleanly.
            return m.group(1).replace("`", "").strip()
    return None


# ----------------------------------------------------------------- git/github

def git_remote_slug(repo_root: str) -> Tuple[str, str]:
    url = run(["git", "-C", repo_root, "remote", "get-url", "origin"])
    m = re.search(r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit("origin does not look like a GitHub remote: {}".format(url))
    return m.group(1), m.group(2)


def blob_url(owner: str, repo: str, branch: str, path: str) -> str:
    return "https://github.com/{}/{}/blob/{}/{}".format(
        owner, repo, branch, path.replace(os.sep, "/"))


def tree_url(owner: str, repo: str, branch: str, path: str) -> str:
    return "https://github.com/{}/{}/tree/{}/{}".format(
        owner, repo, branch, path.replace(os.sep, "/"))


def list_remote_branches(owner: str, repo: str) -> List[str]:
    try:
        out = run(["gh", "api", "--paginate",
                   "repos/{}/{}/branches".format(owner, repo), "--jq", ".[].name"])
        return [b for b in out.split("\n") if b.strip()]
    except RuntimeError:
        return []


def parse_github_url(arg: str, branch_hint: Optional[str] = None):
    """Parse a GitHub /tree/ or /blob/ URL into (owner, repo, ref, path, is_file).

    The awkward part is that ``ref`` may contain slashes -- ``feature/foo`` and
    ``release/sprint-15-2026`` are ordinary branch names -- so the boundary between ref
    and path cannot be found by splitting on '/'. Resolution order:

    1. a ``--branch`` hint that prefixes the remainder,
    2. the longest actual branch name from the API that prefixes it,
    3. the first path segment, which is right only for slash-free refs.

    Returns None when the argument is not a GitHub tree/blob URL.
    """
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/(tree|blob)/(.+?)/?$", arg)
    if not m:
        return None
    owner, repo, kind, rest = m.group(1), m.group(2), m.group(3), m.group(4)

    ref = None
    if branch_hint and (rest == branch_hint or rest.startswith(branch_hint + "/")):
        ref = branch_hint
    else:
        candidates = [b for b in list_remote_branches(owner, repo)
                      if rest == b or rest.startswith(b + "/")]
        if candidates:
            ref = max(candidates, key=len)
    if ref is None:
        ref = rest.split("/")[0]
        warn("could not confirm the branch in {!r}; assuming {!r}. Pass --branch to be "
             "explicit if that is wrong.".format(arg, ref))

    path = rest[len(ref):].lstrip("/")
    is_file = (kind == "blob")
    return owner, repo, ref, path, is_file


# ------------------------------------------------------------------ page model

class Node:
    """One markdown file or folder, and the Confluence page it maps to."""

    def __init__(self, kind: str, rel_path: str, title: str,
                 md_path: Optional[str] = None):
        self.kind = kind            # "folder" | "file"
        self.rel_path = rel_path    # repo-relative, posix
        self.title = title
        self.md_path = md_path      # absolute path to the backing .md, if any
        self.page_id: Optional[str] = None
        self.children: List["Node"] = []
        self.label: str = os.path.basename(rel_path) or rel_path
        self.status: str = "pending"
        self.detail: str = ""


TITLE_SEPARATOR = " - "


def child_title(parent_title: str, basename: str) -> str:
    title = "{}{}{}".format(parent_title, TITLE_SEPARATOR, basename)
    if len(title) > 255:
        warn("title exceeds Confluence's 255-char limit and was truncated: {!r}".format(title))
        title = title[:255]
    return title


def build_tree(abs_folder: str, rel_folder: str, parent_title: str) -> Node:
    """Mirror the folder tree. README.md becomes the folder's own page body."""
    readme = None
    for cand in ("README.md", "readme.md", "Readme.md"):
        p = os.path.join(abs_folder, cand)
        if os.path.isfile(p):
            readme = p
            break

    node = Node("folder", rel_folder.replace(os.sep, "/"), parent_title, readme)
    node.label = first_h1(_read(readme)) if readme else os.path.basename(rel_folder)

    entries = sorted(os.listdir(abs_folder), key=lambda s: s.lower())
    for name in entries:
        full = os.path.join(abs_folder, name)
        if os.path.isdir(full):
            if name in SKIP_DIRS:
                continue
            sub = build_tree(full, os.path.join(rel_folder, name),
                             child_title(parent_title, name))
            node.children.append(sub)
        elif name.lower().endswith(".md") and full != readme:
            base = name[:-3]
            leaf = Node("file", os.path.join(rel_folder, name).replace(os.sep, "/"),
                        child_title(parent_title, base), full)
            leaf.label = first_h1(_read(full)) or base
            node.children.append(leaf)
    return node


def _read(path: Optional[str]) -> str:
    if not path:
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def flatten(node: Node) -> List[Node]:
    out = [node]
    for child in node.children:
        out.extend(flatten(child))
    return out


# -------------------------------------------------------------- storage bodies

def source_panel(owner: str, repo: str, branch: str, rel_path: str,
                 short_sha: str) -> str:
    url = blob_url(owner, repo, branch, rel_path)
    return (
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        '<p><strong>Source:</strong> <a href="{url}">{slug}</a> on <code>{branch}</code></p>'
        '<p>Generated from Markdown by the <code>docs-github-markdown-to-confluence</code> '
        'skill. Edit the source file, not this page &mdash; changes made here are reported '
        'as drift and will not be merged back. Source checksum <code>{sha}</code>.</p>'
        '</ac:rich-text-body></ac:structured-macro>'
    ).format(url=m2s.escape(url),
             slug=m2s.escape("{}/{}/{}".format(owner, repo, rel_path)),
             branch=m2s.escape(branch), sha=short_sha)


def page_structure(node: Node, owner: str, repo: str, branch: str) -> str:
    """Generated index of descendants, in deterministic order.

    Deliberately not the ``children`` macro: under the ``{parent} - {basename}`` title rule
    the child titles are long and near-identical, and a children macro renders them raw.
    Generating the list lets the link text be a clean label while the page keeps its
    prefixed title, and it survives PDF export.
    """
    if not node.children:
        return ""

    def render(items: List[Node]) -> str:
        parts = ["<ul>"]
        for child in items:
            link = m2s.page_link(child.title, child.label)
            src = blob_url(owner, repo, branch, child.rel_path) if child.kind == "file" \
                else tree_url(owner, repo, branch, child.rel_path)
            parts.append('<li>{} &mdash; <a href="{}"><code>{}</code></a>{}</li>'.format(
                link, m2s.escape(src), m2s.escape(child.rel_path),
                render(child.children) if child.children else ""))
        parts.append("</ul>")
        return "".join(parts)

    return "<h2>Page structure</h2>" + render(node.children)


# ---------------------------------------------------------------------- mermaid

def render_mermaid(code: str, out_png: str) -> Tuple[bool, str]:
    """Render with mmdc. Returns (ok, detail)."""
    with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(code)
        src = fh.name
    try:
        mmdc = "mmdc.cmd" if os.name == "nt" else "mmdc"
        run([mmdc, "-i", src, "-o", out_png, "-b", "transparent"])
        return (True, "rendered") if os.path.isfile(out_png) else (False, "mmdc produced no file")
    except RuntimeError as exc:
        return False, str(exc)[:300]
    except FileNotFoundError:
        return False, "mmdc not found on PATH"
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass


# ------------------------------------------------------------------------- main

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync GitHub markdown folders to a Confluence page tree.")
    ap.add_argument("--parent-page", required=True,
                    help="Confluence parent page URL or numeric id")
    ap.add_argument("--folder", action="append",
                    help="local folder path, a GitHub /tree/ URL, or a path/URL naming a "
                         "README.md (its folder is used). Repeatable. Publishes a page "
                         "tree; the folder's README.md becomes the parent page's body, "
                         "and the parent is left untouched if there is no README.md.")
    ap.add_argument("--file", dest="file", default=None,
                    help="a single local .md path or GitHub /blob/ URL to publish as the "
                         "parent page's body. No children, no structure index, no "
                         "deprecation pass. Mutually exclusive with --folder.")
    ap.add_argument("--repo-root", default=None,
                    help="git repo root (default: inferred from the first folder or file)")
    ap.add_argument("--branch", default="master",
                    help="branch that GitHub backlinks point at (default: master). A ref "
                         "in a --folder URL is used to locate the folder, never for links.")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the plan; touch neither Confluence nor the working tree")
    ap.add_argument("--force-parent", action="store_true",
                    help="allow overwriting a parent page we have never synced before")
    ap.add_argument("--no-deprecate", action="store_true",
                    help="do not rename pages whose source markdown has been deleted")
    ap.add_argument("--no-write-back", action="store_true",
                    help="skip injecting the Confluence link into the markdown")
    ap.add_argument("--preview-dir", default=None,
                    help="render the pages to HTML + raw storage here and publish nothing; "
                         "implies --dry-run")
    args = ap.parse_args(argv)

    if args.folder and args.file:
        raise SystemExit("--folder and --file are mutually exclusive: --folder publishes a "
                         "page tree, --file publishes one page")
    if not args.folder and not args.file:
        raise SystemExit("one of --folder (publish a page tree) or --file (publish a single "
                         "markdown file as the parent page) is required")

    if args.preview_dir:
        args.dry_run = True

    client = ConfluenceClient()

    # -- resolve parent -----------------------------------------------------
    parent_id = parse_page_id(args.parent_page)
    parent = client.get_page(parent_id)
    parent_title = parent["title"]
    space_id = str(parent["spaceId"])
    log("Parent page {}: {!r} (version {}, space {})".format(
        parent_id, parent_title, (parent.get("version") or {}).get("number"), space_id))

    # -- resolve the local target(s) ----------------------------------------
    def to_local(raw: str, want: str) -> str:
        """Map one --folder/--file argument to an absolute local path.

        ``want`` is "folder" or "file". A GitHub URL is mapped through --repo-root; a
        plain path is taken as-is. In folder mode a target that names a markdown file
        (README.md, typically) resolves to the folder containing it, so a reader can
        paste either the /tree/ URL of a folder or the /blob/ URL of its README.
        """
        gh = parse_github_url(raw, args.branch)
        if gh:
            _owner, _repo, ref, path, is_file = gh
            if not args.repo_root:
                raise SystemExit(
                    "--repo-root is required when --{} is a GitHub URL".format(want))
            if is_file and want == "folder":
                log("{!r} names a file; syncing the folder that contains it".format(raw))
                path = os.path.dirname(path)
            # A ref in the URL locates the target only. Backlinks deliberately ignore it
            # and use --branch (default master), because a feature branch is deleted when
            # its PR merges, which would break every published link. Pass --branch to
            # point them somewhere else on purpose.
            if ref != args.branch:
                log("URL names branch {!r}; backlinks will still point at {!r}"
                    .format(ref, args.branch))
            return os.path.join(args.repo_root, path.replace("/", os.sep))
        local = os.path.abspath(raw)
        if want == "folder" and os.path.isfile(local) and local.lower().endswith(".md"):
            log("{!r} names a file; syncing the folder that contains it".format(raw))
            return os.path.dirname(local)
        return local

    local_folders: List[str] = []
    local_file: Optional[str] = None

    if args.folder:
        local_folders = [to_local(raw, "folder") for raw in args.folder]
        for folder in local_folders:
            if not os.path.isdir(folder):
                raise SystemExit("not a directory: {}".format(folder))
        anchor = local_folders[0]
    else:
        local_file = to_local(args.file, "file")
        if not os.path.isfile(local_file):
            raise SystemExit("not a file: {}".format(local_file))
        if not local_file.lower().endswith(".md"):
            raise SystemExit("--file must name a .md file: {}".format(local_file))
        anchor = os.path.dirname(local_file)

    repo_root = os.path.abspath(
        args.repo_root or run(["git", "-C", anchor, "rev-parse", "--show-toplevel"]))
    owner, repo = git_remote_slug(repo_root)
    log("Repo: {}/{} (root {}), linking against {!r}".format(owner, repo, repo_root, args.branch))

    # -- build the page tree ------------------------------------------------
    if local_file:
        # Single-file mode: the parent page *is* this file's page. No children, so
        # page_structure() renders nothing and the deprecation pass is skipped below.
        rel = os.path.relpath(local_file, repo_root).replace(os.sep, "/")
        root = Node("file", rel, parent_title, local_file)
        root.label = first_h1(_read(local_file)) or os.path.basename(rel)
        root.page_id = parent_id
        log("Single file {} -> parent page (no children)".format(rel))
    else:
        roots: List[Node] = []
        for folder in local_folders:
            rel = os.path.relpath(folder, repo_root)
            roots.append(build_tree(folder, rel, parent_title))

        # The passed-in page is the parent of everything. When one folder is given, that
        # folder's README becomes the parent body; with several, each folder becomes a child.
        if len(roots) == 1:
            root = roots[0]
            root.title = parent_title
            root.page_id = parent_id
        else:
            root = Node("folder", "", parent_title, None)
            root.page_id = parent_id
            for sub in roots:
                root.children.append(sub)

    all_nodes = flatten(root)
    log("Discovered {} page(s) from {}".format(
        len(all_nodes),
        "1 file" if local_file else "{} folder(s)".format(len(local_folders))))

    # -- first-run guard on the parent --------------------------------------
    existing_prop = client.get_property(parent_id)
    parent_body = ((parent.get("body") or {}).get("storage") or {}).get("value") or ""
    # Only a guard against *replacing* the parent body. With no README.md in folder mode
    # the parent is never written, so there is nothing to protect it from.
    if (root.md_path and existing_prop is None and parent_body.strip()
            and not args.force_parent and not args.preview_dir):
        backup = os.path.join(tempfile.gettempdir(),
                              "confluence-page-{}-backup.xhtml".format(parent_id))
        with open(backup, "w", encoding="utf-8") as fh:
            fh.write(parent_body)
        log("")
        log("REFUSING to overwrite the parent page.")
        log("  Page {} ({!r}) already has {} chars of content and has never been synced".format(
            parent_id, parent_title, len(parent_body)))
        log("  by this skill, so the source markdown would replace hand-written content.")
        log("  Existing body saved to: {}".format(backup))
        log("  Re-run with --force-parent to proceed, or point --parent-page at a new page.")
        return 2

    # ============================ pass A: ensure pages exist ================
    # Every page must exist before any body is converted, because relative .md links can
    # only be turned into real page links once each target's title is known to exist.
    existing_children: Dict[str, Dict] = {}

    def index_children(page_id: str) -> None:
        try:
            for child in client.get_child_pages(page_id):
                existing_children[child["title"]] = child
        except ConfluenceError as exc:
            warn("could not list children of {}: HTTP {}".format(page_id, exc.status))

    index_children(parent_id)
    for node in all_nodes:
        if node.page_id:
            index_children(node.page_id)

    def ensure(node: Node, parent_page_id: str) -> None:
        if node.status == "skipped":
            return
        if node.page_id is None:
            found = existing_children.get(node.title)
            if found:
                node.page_id = str(found["id"])
            elif args.dry_run:
                node.status = "would-create"
                return
            else:
                created = client.create_page(space_id, parent_page_id, node.title,
                                            "<p>Placeholder; body follows.</p>")
                node.page_id = str(created["id"])
                node.status = "created"
                index_children(node.page_id)
        for child in node.children:
            ensure(child, node.page_id or parent_page_id)

    ensure(root, parent_id)

    # -- title -> node, for link resolution --------------------------------
    by_rel: Dict[str, Node] = {n.rel_path: n for n in all_nodes if n.rel_path}

    def make_resolver(node: Node):
        # A folder node is backed by its own README.md, so relative links in that body are
        # relative to the folder itself -- not to its parent, which is what dirname() gives.
        # Getting this wrong leaves every README -> sibling link as a dead relative href.
        base_dir = node.rel_path if node.kind == "folder" else os.path.dirname(node.rel_path)

        def resolve(href: str):
            if href.startswith(("http://", "https://", "mailto:", "#")):
                return None
            path_part, _, fragment = href.partition("#")
            if not path_part:
                return None
            target = os.path.normpath(os.path.join(base_dir, path_part)).replace(os.sep, "/")
            if path_part.endswith(".md"):
                # Resolve by *title*: ac:link targets ri:content-title, not an id, so a page
                # need not exist yet for the link to be correct. Requiring page_id here would
                # make every internal link degrade during --dry-run and --preview-dir.
                hit = by_rel.get(target)
                if hit:
                    return ("page", hit.title)
                # A README maps onto its folder's page rather than a page of its own.
                folder = os.path.dirname(target)
                if os.path.basename(target).lower() == "readme.md":
                    hit = by_rel.get(folder)
                    if hit:
                        return ("page", hit.title)
            # Not a synced page: a source file, or a doc outside the folders being synced.
            # A relative href is meaningless from a Confluence page -- it resolves against
            # the wiki URL, not the repo -- so point at the file on GitHub instead. Docs
            # that cite source files are mostly links, and emitting them verbatim is the
            # difference between a useful page and one full of links that quietly 404.
            url = blob_url(owner, repo, args.branch, target)
            if fragment:
                url += "#" + fragment
            return ("url", url)

        return resolve

    # ============================ pass B: convert and publish ==============
    attachment_supported: Optional[bool] = None
    results: List[Node] = []
    preview_pages: List[Tuple[str, str, str, str]] = []

    for node in all_nodes:
        if node.status == "skipped":
            results.append(node)
            continue
        if not node.md_path:
            # No README.md backs this folder, so there is no body to publish. Leave the
            # page exactly as it is rather than replacing whatever a human put there with
            # a bare structure index -- children are still published beneath it.
            node.status = "skipped"
            node.detail = "no README.md in {}; page left untouched".format(
                node.rel_path or "the folder")
            results.append(node)
            continue
        source_md = _read(node.md_path)
        src_sha = sha256(strip_managed_block(source_md)) if node.md_path else sha256(node.title)

        prop = client.get_property(node.page_id) if node.page_id else None
        stored = (prop or {}).get("value") or {}

        live_page = None
        drifted = False
        if node.page_id and not args.dry_run:
            live_page = client.get_page(node.page_id)
            live_body = ((live_page.get("body") or {}).get("storage") or {}).get("value") or ""
            if stored.get("publishedSha256") and sha256(live_body) != stored["publishedSha256"]:
                drifted = True

        # The GitHub coordinates are part of the key, not just recorded output: they are
        # rendered into the source panel and the structure index, so a changed --branch,
        # repo or path must force a rebuild. Leaving them out meant `--branch master` was
        # silently ignored for pages already synced against a feature branch.
        unchanged = (stored.get("sourceSha256") == src_sha
                     and stored.get("converterVersion") == m2s.CONVERTER_VERSION
                     and stored.get("structureSha256") is not None
                     and stored.get("githubBranch") == args.branch
                     and stored.get("githubRepo") == "{}/{}".format(owner, repo)
                     and stored.get("githubPath") == (node.rel_path or ""))

        if drifted:
            node.status = "drifted"
            node.detail = ("live page differs from what we last published; skipped so a "
                           "human decides. Re-publish by editing the source, or delete the "
                           "'{}' property to force.".format("githubMarkdownSync"))
            results.append(node)
            continue

        # ---- mermaid handling: always emit source, add an image when possible ----
        pending_uploads: List[Tuple[str, bytes]] = []
        stored_diagrams: Dict[str, str] = dict(stored.get("diagramShas") or {})
        new_diagrams: Dict[str, str] = {}
        existing_atts = (client.list_attachments(node.page_id)
                         if node.page_id and not args.dry_run else {})

        def mermaid_handler(code: str, index: int, _node=node) -> str:
            nonlocal attachment_supported
            source_block = m2s.code_macro(code, "text",
                                          title="Mermaid source", collapse=True)
            # Filenames are stable rather than content-addressed, so the page body does
            # not change when only a diagram does -- the attachment is replaced in place.
            fname = "{}-mermaid-{}.png".format(
                re.sub(r"[^A-Za-z0-9_.-]", "-", os.path.basename(_node.rel_path or "page")),
                index)
            code_sha = sha256(code)
            new_diagrams[fname] = code_sha

            if args.dry_run or attachment_supported is False:
                return source_block

            # Unchanged diagram that is already attached: reference it and skip both the
            # render and the upload, so re-syncing a page for an unrelated edit does not
            # add a pointless attachment version.
            if stored_diagrams.get(fname) == code_sha and fname in existing_atts:
                return m2s.attachment_image(fname, "Diagram") + source_block

            out_png = os.path.join(tempfile.gettempdir(), fname)
            ok, detail = render_mermaid(code, out_png)
            if not ok:
                warn("mermaid render failed ({}); emitting source only".format(detail))
                new_diagrams.pop(fname, None)
                return source_block
            with open(out_png, "rb") as fh:
                data = fh.read()
            try:
                os.unlink(out_png)
            except OSError:
                pass
            pending_uploads.append((fname, data))
            return m2s.attachment_image(fname, "Diagram") + source_block

        conv = m2s.Converter(link_resolver=make_resolver(node),
                             mermaid_handler=mermaid_handler,
                             warn=lambda m, _n=node: warn("{}: {}".format(_n.rel_path or _n.title, m)))
        # Strip the managed block before converting, not just before checksumming. It is a
        # GitHub-side affordance -- a link from the Markdown to the page you are already
        # looking at -- and its <sub> tag is inline HTML the converter can only escape. Left
        # in, every published page carries a link to itself and a literal &lt;sub&gt;.
        body_md = conv.convert(strip_managed_block(source_md)) if node.md_path else ""

        rel_for_link = node.rel_path or ""
        panel = source_panel(owner, repo, args.branch, rel_for_link, src_sha[:12]) \
            if node.md_path else ""
        structure = page_structure(node, owner, repo, args.branch)
        full_body = panel + body_md + structure
        structure_sha = sha256(structure)

        if args.preview_dir:
            node.status = "preview"
            preview_pages.append((node.title, node.rel_path, "preview", full_body))
            results.append(node)
            continue

        if unchanged and stored.get("structureSha256") == structure_sha:
            node.status = "unchanged"
            results.append(node)
            continue

        if args.dry_run:
            node.status = node.status if node.status == "would-create" else "would-update"
            results.append(node)
            continue

        # Upload attachments before the body references them. PUT upserts, so a changed
        # diagram replaces the existing file rather than duplicating it.
        for fname, data in pending_uploads:
            ok, detail = client.upload_attachment(node.page_id, fname, data)
            if ok:
                attachment_supported = True
            else:
                if attachment_supported is None:
                    warn("attachment upload unavailable: {}".format(detail))
                attachment_supported = False
                new_diagrams.pop(fname, None)
                full_body = full_body.replace(m2s.attachment_image(fname, "Diagram"), "")

        version = ((live_page or client.get_page(node.page_id)).get("version") or {}).get("number", 1)
        try:
            client.update_page(node.page_id, node.title, full_body, int(version),
                               message="Synced from {}/{} {}".format(owner, repo, rel_for_link))
        except ConfluenceError as exc:
            node.status = "error"
            node.detail = "HTTP {}: {}".format(exc.status, exc.body[:200])
            results.append(node)
            continue

        refreshed = client.get_page(node.page_id)
        published = ((refreshed.get("body") or {}).get("storage") or {}).get("value") or ""
        client.set_property(node.page_id, {
            "sourceSha256": src_sha,
            "publishedSha256": sha256(published),
            "structureSha256": structure_sha,
            "converterVersion": m2s.CONVERTER_VERSION,
            "githubPath": rel_for_link,
            "githubRepo": "{}/{}".format(owner, repo),
            "githubBranch": args.branch,
            # filename -> sha256 of the Mermaid source, so an unchanged diagram is not
            # re-rendered or re-uploaded on the next sync
            "diagramShas": new_diagrams,
        })
        node.status = "created" if node.status == "created" else "updated"
        results.append(node)

    # ==================== deprecate orphaned pages ==========================
    # A page whose source markdown has been deleted is renamed, not removed: the content
    # may still be referenced or worth reading, and deleting someone's wiki page because a
    # file moved is not a call this should make silently.
    # Single-file mode never runs it: one file says nothing about what else belongs under
    # that page, so treating every existing child as orphaned would rename pages a
    # different sync owns.
    if not args.no_deprecate and not local_file:
        expected = {n.title for n in all_nodes}

        def descendants(page_id: str, depth: int = 0) -> List[Dict]:
            if depth > 6:  # guard against a pathological tree
                return []
            found: List[Dict] = []
            try:
                for child in client.get_child_pages(page_id):
                    found.append(child)
                    found.extend(descendants(str(child["id"]), depth + 1))
            except ConfluenceError as exc:
                warn("could not list children of {}: HTTP {}".format(page_id, exc.status))
            return found

        for page in descendants(parent_id):
            title = page.get("title") or ""
            page_id = str(page["id"])
            if title in expected or title.startswith(DEPRECATED_PREFIX):
                continue
            # Only ever touch pages this skill published. A hand-made child page under the
            # same parent has no sync property, and renaming it would be vandalism.
            try:
                if client.get_property(page_id) is None:
                    continue
            except ConfluenceError:
                continue

            new_title = DEPRECATED_PREFIX + title
            if len(new_title) > 255:
                new_title = new_title[:255]

            orphan = Node("file", "", new_title)
            orphan.label = title
            if args.dry_run:
                orphan.status = "would-deprecate"
                orphan.detail = "source markdown is gone; would rename {!r}".format(title)
                results.append(orphan)
                continue
            try:
                client.rename_page(page_id, new_title)
                orphan.status = "deprecated"
                orphan.detail = "source markdown is gone; renamed from {!r}".format(title)
            except ConfluenceError as exc:
                orphan.status = "error"
                orphan.detail = "rename failed for {!r}: HTTP {}".format(title, exc.status)
            results.append(orphan)

    # ============================ write-back (local only) ==================
    touched: List[str] = []
    if not args.no_write_back and not args.dry_run:
        for node in all_nodes:
            if node.status in ("skipped", "drifted", "error") or not node.md_path:
                continue
            page = client.get_page(node.page_id)
            url = client.page_web_url(page)
            block = (
                "{start}\n"
                "> **Published to Confluence:** [{title}]({url})\n"
                ">\n"
                "> <sub>This block is managed by the `docs-github-markdown-to-confluence` "
                "skill and is excluded from its checksum. Edits to it are overwritten.</sub>\n"
                "{end}\n"
            ).format(start=BLOCK_START, title=node.title, url=url, end=BLOCK_END)

            original = _read(node.md_path)
            stripped = BLOCK_RE.sub("", original)
            lines = stripped.split("\n")
            insert_at = 0
            for idx, line in enumerate(lines):
                if re.match(r"^#\s+", line):
                    insert_at = idx + 1
                    break
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            new_md = "\n".join(lines[:insert_at] + ["", block.rstrip("\n"), ""] + lines[insert_at:])
            new_md = re.sub(r"\n{3,}", "\n\n", new_md)
            if new_md != original:
                with open(node.md_path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(new_md)
                touched.append(os.path.relpath(node.md_path, repo_root))

    # ============================ report ===================================
    log("")
    log("{:<10} {:<52} {}".format("STATUS", "PAGE TITLE", "SOURCE"))
    log("-" * 110)
    for node in results:
        log("{:<10} {:<52} {}".format(node.status, node.title[:52],
                                      node.rel_path or "(generated)"))
        if node.detail:
            log("           -> {}".format(node.detail))

    counts: Dict[str, int] = {}
    for node in results:
        counts[node.status] = counts.get(node.status, 0) + 1
    log("")
    log("Summary: " + ", ".join("{} {}".format(v, k) for k, v in sorted(counts.items())))

    if args.preview_dir and preview_pages:
        import preview as preview_mod
        written = preview_mod.write_preview(
            os.path.abspath(args.preview_dir), preview_pages,
            "Confluence preview: {}".format(parent_title),
            "{} page(s) from {}/{} -- nothing was published".format(
                len(preview_pages), owner, repo))
        log("")
        log("Preview written ({} page(s)), nothing published:".format(len(preview_pages)))
        log("  {}".format(written["__index__"]))
        log("  raw storage XHTML alongside it, one file per page")

    if attachment_supported is False:
        log("")
        log("Mermaid diagrams were published as source only: attachment upload was rejected.")
        log("Add 'write:attachment:confluence' AND 'read:content-details:confluence' to the")
        log("API token to enable rendered images -- the upload endpoint is v1 and needs both.")

    if touched:
        log("")
        log("Modified {} markdown file(s) in the working tree -- NOT committed:".format(len(touched)))
        for path in touched:
            log("  {}".format(path))
        log("")
        log("Review, then commit yourself:")
        log("  git -C {} diff -- {}".format(repo_root, " ".join(touched)))
        log("  git -C {} checkout -b docs/confluence-links".format(repo_root))
        log("  git -C {} add {}".format(repo_root, " ".join(touched)))
        log('  git -C {} commit -m "Add Confluence page links to docs"'.format(repo_root))
    elif not args.dry_run and not args.no_write_back:
        log("")
        log("No markdown files needed changing.")

    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
