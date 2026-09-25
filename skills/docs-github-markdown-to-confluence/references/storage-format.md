# Confluence storage format: mapping notes and gotchas

Reference for `md_to_storage.py`. Storage format is XHTML plus Confluence's `ac:` and `ri:`
namespaces. It is **not** HTML: unknown tags are stripped or rejected, and the document
must be well-formed XML.

## Verifying output

Storage format is not valid standalone XML, because `ac:` and `ri:` prefixes are undeclared.
Wrap it before parsing:

```python
import xml.etree.ElementTree as ET
ET.fromstring('<root xmlns:ac="a" xmlns:ri="r">' + storage + '</root>')
```

That catches unbalanced tags and bad escaping, which are the failures that make a `PUT`
return 400. It does **not** validate that macros exist or take the parameters given.

## Mapping

| Markdown | Storage format |
|---|---|
| `# H1` .. `###### H6` | `<h1>` .. `<h6>` |
| paragraph | `<p>` |
| `**bold**` | `<strong>` |
| `*italic*`, `_italic_` | `<em>` |
| `~~strike~~` | `<s>` |
| `` `code` `` | `<code>` |
| ` ```lang ` fence | `code` macro with `language` parameter, body in CDATA |
| pipe table | `<table><tbody><tr><th>/<td>` |
| `- item` / `1. item` | `<ul>` / `<ol>` with `<li>` |
| `> quote` | `<blockquote>` |
| `---` | `<hr/>` |
| `[text](https://…)` | `<a href="…">` |
| `[text](sibling.md)` | `ac:link` -> `ri:page` (see below) |
| `![alt](https://…)` | `ac:image` -> `ri:url` |
| `![alt](relative.png)` | left as `<a>` + warning; needs an attachment |
| `<!-- comment -->` | dropped |

## Snippets

Code macro. The body **must** be CDATA, and a literal `]]>` inside the code has to be split
or it terminates the section early:

```xml
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">java</ac:parameter>
  <ac:parameter ac:name="collapse">true</ac:parameter>
  <ac:plain-text-body><![CDATA[ ... ]]></ac:plain-text-body>
</ac:structured-macro>
```

Internal page link, by title. Confluence resolves it at render time, so the target must
already exist -- hence the two-pass design in `sync_confluence.py`:

```xml
<ac:link>
  <ri:page ri:content-title="Parent Title-child"/>
  <ac:plain-text-link-body><![CDATA[Clean label]]></ac:plain-text-link-body>
</ac:link>
```

Attached image, and an externally-hosted one:

```xml
<ac:image ac:alt="Diagram"><ri:attachment ri:filename="diagram.png"/></ac:image>
<ac:image ac:alt="Diagram"><ri:url ri:value="https://example.com/d.png"/></ac:image>
```

Info panel:

```xml
<ac:structured-macro ac:name="info">
  <ac:rich-text-body><p>…</p></ac:rich-text-body>
</ac:structured-macro>
```

## Gotchas

**Escaping.** `&`, `<`, `>` must be escaped in text. Escape `&` first or you double-escape
the entities you just wrote. Do not escape inside CDATA -- it is already literal.

**`ri:url` needs a publicly fetchable URL.** Confluence's server fetches it, so
`raw.githubusercontent.com` on a *private* repo renders broken. Private-repo images have to
be attachments.

**Attachments are v1-only** for create and update, with header
`X-Atlassian-Token: no-check`. v2 can *list* them, but
`GET /api/v2/pages/{id}/attachments` requires `read:attachment:confluence` — a scope you
would otherwise not need — so prefer the v1 listing
(`GET /rest/api/content/{id}/child/attachment`), already covered by
`read:content-details:confluence`.

| Verb | Path | Behaviour |
|---|---|---|
| `PUT` | `/rest/api/content/{id}/child/attachment` | **upsert by filename** — use this |
| `POST` | `/rest/api/content/{id}/child/attachment` | add only; a repeat filename duplicates |
| `POST` | `/rest/api/content/{id}/child/attachment/{attId}/data` | replace one known attachment |

Use `PUT` unless you already hold the attachment id. All three want the same granular pair
— `write:attachment:confluence` *and* `read:content-details:confluence` — or the classic
`write:confluence-file`. Replacement needs no extra permission over creation.

The second granular scope is the one people miss: a token scoped for v2 page work has
`read:page:confluence`, which v1 does not accept, so the upload 401s even though the write
scope is present. v1 and v2 want different scope families for the same underlying data.

**Same-page anchors don't port.** `[x](#heading)` has no portable storage equivalent; the
converter keeps the link text and drops the link.

**Titles are unique per space** and capped at 255 characters. A `PUT` that collides with
another page's title fails.

**`PUT` needs the next version number**, i.e. current + 1. A stale number is a 409, which
is the optimistic lock doing its job — re-read the page and retry.

**Macro availability varies.** `code`, `info`, `children` and `toc` are built in. Anything
else depends on installed apps, which you cannot enumerate with a scoped token because
`/rest/plugins` is v1.

## Why the structure index is generated, not a `children` macro

`<ac:structured-macro ac:name="children"/>` renders raw child titles. Under the
`{parent-title} - {basename}` rule those are long and near-identical, so the list reads as a
column of nearly the same 50-character string. Generating the list allows a clean label per
entry while the page keeps its prefixed title, adds the GitHub source link alongside, and
survives PDF export. The cost is that it must be regenerated when files are added or
removed — which is why `structureSha256` is part of the skip decision.
