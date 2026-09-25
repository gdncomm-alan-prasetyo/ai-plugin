---
name: docs-github-markdown-to-confluence
description: >
  Publishes GitHub Markdown to Confluence and keeps the two cross-linked. Given a folder, its
  README.md becomes the parent page and every other .md becomes a child; a folder with no
  README.md leaves the parent untouched. Given a single .md file, that file becomes the
  parent page body and nothing else is created. Unchanged files are skipped by checksum.
  Injects the Confluence link back into the Markdown locally and never commits. Use to
  "publish docs to Confluence", "sync markdown to Confluence", or mirror a docs folder into
  a wiki space.
argument-hint: "<confluence-page-url> <folder-or-markdown-file> [--dry-run]"
allowed-tools: ["Bash(python*)", "Bash(git*)", "Bash(gh*)", "Read", "Glob", "Grep", "Write", "Edit"]
---

# GitHub Markdown -> Confluence

Publishes Markdown to Confluence idempotently, and links the two directions so a reader
who lands on either side can find the other. The hard parts are not the conversion; they
are **not republishing unchanged pages**, **not destroying hand-written content**, and
**not emitting links that 404**. Each has a mechanism below, and each can bite if you
bypass it.

## Prerequisites

A **Confluence API token** and these environment variables (they live in
`~/.claude/settings.json` under `env`, so a new session has them already):

```
CONFLUENCE_EMAIL      CONFLUENCE_API_TOKEN
CONFLUENCE_CLOUD_ID   CONFLUENCE_SITE_URL
```

Token scopes:

| Scope | Needed for | API |
|---|---|---|
| `read:page:confluence` | read a page, list child pages, read the sync property | v2 |
| `write:page:confluence` | create/update pages, write the sync property | v2 |
| `write:attachment:confluence` | upload/replace rendered Mermaid images | v1 |
| `read:content-details:confluence` | **also** required by that upload, and by listing existing attachments | v1 |

Four, and no more. `read:attachment:confluence` is deliberately **not** needed: attachments
are listed through the v1 endpoint, which `read:content-details:confluence` already covers,
rather than through `GET /api/v2/pages/{id}/attachments`, which would demand that fifth
scope for the same data.

**Scoped tokens only work against the `api.atlassian.com/ex/confluence/<cloudId>/wiki`
gateway** -- the `<site>.atlassian.net` host returns 401 for them.

**v1 and v2 need different granular scopes for the same data.** A token scoped for v2 page
work gets 401 from every v1 endpoint, which looks like "v1 rejects scoped tokens" but is
just a missing scope. This is why attachment upload needs
`read:content-details:confluence` on top of the write scope: it is a v1 endpoint, and
`read:page:confluence` does not satisfy it.

`gh` (for the branch-presence check) and `mmdc` (for Mermaid rendering) are optional.
Both degrade with a warning rather than failing the run.

## Two modes

Exactly one of `--folder` or `--file` is required; passing both is an error.

| | `--folder <folder>` | `--file <one.md>` |
|---|---|---|
| Publishes | a page tree | exactly one page |
| Parent page body | the folder's `README.md`, or **untouched** if there is none | that file |
| Children | one per `.md` and per subfolder | none |
| Structure index | generated at the bottom of each folder page | none |
| Deprecation pass | runs | **does not run** |

**Folder mode** accepts either the folder itself or a path/URL naming a Markdown file
inside it -- `docs/database`, `.../tree/master/docs/database`, `docs/database/README.md`
and `.../blob/master/docs/database/README.md` all sync the same folder. Pass `--folder`
more than once and each folder becomes a child of the parent instead, with the parent's
own body left alone -- literally untouched, since the synthetic root that holds several
folders has no `README.md` and therefore falls under the rule above. It is reported
`skipped`, and the parent gets no generated index of the folders beneath it.

**Single-file mode** is for a doc that has no folder of its own -- one `architecture.md`
onto one wiki page. It creates nothing besides that page. The deprecation pass is
deliberately skipped: a lone file says nothing about what else belongs under the parent,
so treating every existing child as orphaned would rename pages a different sync owns.

## Workflow

1. **Always dry-run first.** It touches neither Confluence nor the working tree:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/docs-github-markdown-to-confluence/scripts/sync_confluence.py \
     --parent-page "<confluence page url or id>" --folder docs/database --dry-run
   ```

   Or for a single file:

   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/skills/docs-github-markdown-to-confluence/scripts/sync_confluence.py \
     --parent-page "<confluence page url or id>" --file docs/architecture.md --dry-run
   ```

2. **Read the report before the real run.** Every page is reported as `created`,
   `updated`, `unchanged`, `deprecated`, `skipped`, `drifted`, or `error`, with a reason.

3. **Drop `--dry-run`** to publish. Then review the Markdown it changed with `git diff`
   and commit yourself -- see *Write-back* below.

Run it from anywhere; paths are resolved against the repo root inferred from the target.

## Mapping (folder mode)

| Markdown | Confluence |
|---|---|
| the folder you pass | the page you pass (`--parent-page`) |
| that folder's `README.md` | **the parent page's body** |
| *no* `README.md` in that folder | the parent page is **left exactly as it is** |
| any other `foo.md` | child page titled `{parent-title} - foo` |
| a subfolder | child page titled `{parent-title} - {foldername}`, nesting recursively |
| a subfolder's `README.md` | that subfolder page's body |

Child titles are prefixed with the parent's title joined by `" - "` (the separator is
`TITLE_SEPARATOR` in `sync_confluence.py`). That prefix is what keeps `docs/api/README.md`
and `docs/database/README.md` from colliding -- Confluence titles are unique per space. It
also makes titles long; the script truncates at 255 chars and warns.

Renaming the separator **renames every page**: titles are the identity used to find
existing children, so a changed separator makes the old pages invisible to the skill and it
creates a fresh set beside them. Change it before a first publish, not after.

### A folder with no README.md

The page is reported `skipped` and **nothing is written to it** -- not the body, not the
source panel, not the structure index. Children are still created beneath it.

This is the deliberate choice over the obvious alternative of writing a bare structure
index: a parent page without a README is usually one a human wrote by hand, and replacing
their content with a generated list of links is exactly the destruction this skill exists
to avoid. The cost is that such a parent has no generated navigation to its children --
Confluence's own page tree is the only path down. Add a `README.md` if you want one.

## The three mechanisms that matter

### Checksums, and why the managed block is excluded

Each page stores a `githubMarkdownSync` **content property** holding `sourceSha256`,
`publishedSha256`, `structureSha256`, `converterVersion`, and the GitHub coordinates
(`githubRepo`, `githubBranch`, `githubPath`). A page is skipped only when **all** of those
match.

The coordinates are part of the key, not just a record of what was published, and this was
a real bug: they are rendered into the source panel and the structure index, so a changed
`--branch` must force a rebuild. While they were excluded, re-running with `--branch master`
against pages synced from a feature branch reported `unchanged` and quietly left every
backlink pointing at the old branch.

The source hash is taken **with the managed block stripped**. This is not cosmetic: the
script injects the Confluence link *into* the Markdown, which changes the file. Hashing
the whole file would mean publish -> inject -> file differs -> republish, forever, and
"skip if unchanged" would never once fire.

Stripping alone is not enough, and this was a real bug caught by running the sync twice.
Removing the block leaves the blank lines that surrounded it, so
`heading\n\ntext` strips back to `heading\n\n\ntext` -- one extra blank line, a different
hash, republish forever. Injection also adds a blank line after the heading whether or not
the author had one, and no amount of collapsing turns two newlines back into one. So
`strip_managed_block` normalises **both** sides to one convention: exactly one blank line
after a heading, no runs of three or more newlines. Change that function and re-run the sync
twice; the second run must report `unchanged`.

`converterVersion` is stored for the mirror-image problem: hashing only the source means a
later improvement to `md_to_storage.py` republishes nothing, freezing every page on the
old rendering. Bump `CONVERTER_VERSION` and every page rebuilds.

### The first-run guard on the parent page

Because the source Markdown **replaces the parent page's body**, pointing this at an
existing hand-written page would destroy it. So: if the parent has content but no sync
property from us, the script **refuses**, saves the existing body to a backup file, and
tells you the path. `--force-parent` overrides.

The guard only fires when the parent body is actually going to be written -- a folder with
no `README.md` never reaches it, because nothing would be replaced.

Prefer creating a fresh empty page as the parent on a first run. Overriding the guard on a
page someone wrote by hand is a one-way trip -- the backup is a local temp file, not a
Confluence version.

### Backlinks always point at `master`

Backlinks use `--branch`, which defaults to `master`, and **nothing is verified** -- the
skill does not check whether the file exists on that branch before linking to it.

A ref inside a `--folder` or `--file` URL locates the target and is otherwise **ignored**
for links. So passing `.../blob/feature/my-branch/docs/database/README.md` reads that
folder but still links to `master`, and says so in the output. That is deliberate: a
feature branch is deleted when its PR merges, which would break every published link.
Linking to `master` means links are briefly premature rather than permanently broken.

Pass `--branch` to point them somewhere else on purpose.

## Deleted Markdown: pages are deprecated, not removed

When a `.md` file is gone but its Confluence page still exists, the page is **renamed** with
a `[DEPRECATED] - ` prefix and reported as `deprecated`. It is never deleted: the content may
still be linked or worth reading, and removing someone's wiki page because a file moved is
not a call this should make silently. Delete it yourself once you have looked.

Two safeguards:

- **Only pages this skill published are touched.** A page without a `githubMarkdownSync`
  property is left alone, so a hand-made child page under the same parent is never renamed.
- **Idempotent.** An already-prefixed title is skipped, so re-running does not produce
  `[DEPRECATED] - [DEPRECATED] - …`.

`--no-deprecate` turns it off, and **single-file mode never runs this pass at all** --
see *Two modes* above for why. `--dry-run` reports `would-deprecate` without renaming.

Because the title *is* the identity, restoring the Markdown later creates a **new** page at
the original title and leaves the deprecated one beside it. Rename or delete the old one by
hand if you want them merged.

## Drift

`publishedSha256` records what the script last wrote. If the live page no longer matches,
someone edited it in Confluence, and the page is reported `drifted` and **skipped** --
never overwritten. Resolve by folding the edit into the Markdown source, or delete the
page's `githubMarkdownSync` property to force a republish and discard it.

## Mermaid

Two paths, chosen at runtime:

- Source is **always** emitted, in a collapsed code macro, so nothing is lost.
- The script additionally renders with `mmdc`, uploads a PNG, and embeds it.

Attachment upload exists only on the **v1** API and needs **both**
`write:attachment:confluence` and `read:content-details:confluence`. Missing either, the
upload 401s, the run falls back to source-only, and the report names the scopes to add. No
skill change is needed either way -- add the scopes and images start appearing.

### Replacing a changed diagram

Uploads use `PUT /child/attachment`, which **upserts by filename**: Confluence matches the
name and adds a new version. The `POST` on the same path only ever *adds*, so a re-sync of
a changed diagram through it would accumulate duplicates instead of replacing. Replacement
needs no extra scopes -- the same two cover it.

Filenames are **stable**, not content-addressed (`role.md-mermaid-1.png`), so changing a
diagram does not change the page body -- only the attachment gains a version. The
alternative, hashing the content into the filename, would avoid replacement entirely but
would leave an orphan file behind on every edit and rewrite the body each time.

To avoid pointless attachment versions, the sync property stores `diagramShas`, a
filename -> Mermaid-source hash map. An unchanged diagram on an otherwise-changed page is
neither re-rendered nor re-uploaded; the body just references the attachment already there.
`mmdc` is slow enough that this is worth it on its own.

## Write-back: local only, never commits

The script rewrites each Markdown file in the working tree, inserting after the first `#`
heading:

```markdown
<!-- confluence-sync:start -->
> **Published to Confluence:** [Title](https://.../wiki/spaces/.../pages/123/Title)
<!-- confluence-sync:end -->
```

It stages nothing, commits nothing, and creates no branch or PR. It prints the `git diff`
and commit commands for you to run. `--no-write-back` skips the injection entirely.

The block is **stripped before conversion**, so it never reaches Confluence -- it is a
GitHub-side affordance, and a page linking to itself is noise. It is also excluded from the
checksum, so injecting it does not mark the file as changed.

On the Confluence side each page gets a matching info panel linking to the source file on
`--branch`, plus the short source checksum.

## Options

| Flag | Effect |
|---|---|
| `--parent-page` | Confluence page URL or numeric id (required) |
| `--folder` | local path, GitHub `/tree/` URL, or a path/URL naming a Markdown file inside the folder; repeatable. One of `--folder`/`--file` is required |
| `--file` | a single local `.md` path or GitHub `/blob/` URL, published as the parent page's body; no children, no structure index, no deprecation pass |
| `--repo-root` | git root; required when `--folder`/`--file` is a URL, else inferred |
| `--branch` | branch backlinks point at (default `master`); a ref in a `--folder`/`--file` URL never overrides it |
| `--dry-run` | report the plan, change nothing |
| `--force-parent` | override the first-run guard |
| `--no-deprecate` | leave pages alone when their source Markdown is deleted |
| `--no-write-back` | do not touch the Markdown |
| `--preview-dir` | render pages to HTML + raw storage locally; implies `--dry-run` |

## Conversion limits

`md_to_storage.py` is hand-written -- there is no Markdown library in this environment.
It supports ATX headings, paragraphs, GFM pipe tables, fenced code, nested lists,
blockquotes, rules, HTML comments, and `**bold**` / `*italic*` / `` `code` `` / links /
images. Everything else **warns** rather than converting silently.

Not supported, and the reason each one matters when authoring the Markdown upstream:

| Construct | What happens |
|---|---|
| YAML front matter | `---` is a horizontal rule. Front matter renders as a rule, a visible paragraph of `key: value`, and another rule. Never put metadata there. |
| Inline HTML (`<details>`, `<sub>`, `<br>`) | Escaped. The reader sees `&lt;details&gt;`. Only `<!-- comments -->` are handled, and they are dropped. |
| Same-page anchors `[x](#heading)` | Storage format has no portable same-page anchor, so the link is dropped and only the label text survives. **Link to a file, not an anchor** -- `[x](./README.md)` becomes a real page link. A cross-file link with a fragment keeps the page link and drops the fragment. |
| Setext headings, reference-style links, footnotes, nested tables, task lists | Warn, no conversion. |

Two more specifics:

- A cell containing an unescaped `|` produces too many columns. The surplus is **merged
  into the last column** and warned about, because dropping it would silently lose text.
- Relative `[x.md](x.md)` links become real Confluence page links, which is why every page
  is created before any body is converted. A relative *image* cannot be resolved and stays
  a link, with a warning.

**Read the warnings on stderr.** A silent run means clean conversion; a noisy one means
check those pages before trusting them.

Skills that generate Markdown for publication here follow
`~/.claude/references/doc-output-conventions.md`, which restates these limits as authoring
rules.

## Files

| Path | Role |
|---|---|
| `scripts/sync_confluence.py` | orchestrator and CLI |
| `scripts/md_to_storage.py` | Markdown -> storage format; owns `CONVERTER_VERSION` |
| `scripts/confluence_client.py` | v2 API client; run it directly to self-check a token |
| `references/storage-format.md` | storage-format mapping notes and gotchas |

Token self-check:

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/docs-github-markdown-to-confluence/scripts/confluence_client.py 2190148405
```
