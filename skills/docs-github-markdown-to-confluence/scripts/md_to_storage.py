"""Markdown -> Confluence storage format, for a deliberately limited subset.

There is no markdown library in this environment (no ``markdown``, ``mistune``,
``commonmark``, ``bs4``), so this is a hand-written converter. It therefore supports a
*documented subset* and reports anything it does not understand through ``warn`` rather
than silently mangling it. That tradeoff is the point: a wrong-but-quiet conversion of a
schema document is worse than a loud gap.

Supported: ATX headings, paragraphs, GFM pipe tables, fenced code blocks (including
``mermaid``), nested unordered/ordered lists, blockquotes, horizontal rules, HTML
comments, and the inline set ``**bold**``, ``*italic*``/``_italic_``, `` `code` ``,
``[text](url)``, ``![alt](url)``.

Not supported (each raises a warning): setext headings, reference-style links, footnotes,
nested tables, inline HTML other than comments, task lists, definition lists, and tables
whose cells contain a literal ``|``.

Bump CONVERTER_VERSION on any change that alters output for unchanged input. The sync
script stores it next to the source checksum, so a bump forces every page to rebuild --
without it, improving this file would leave already-published pages frozen on the old
rendering. This also covers changes in sync_confluence.py that alter how a page body is
assembled: nothing else in the stored property tracks them, so a body-assembly change
needs a bump here or already-published pages keep the old rendering forever.
"""

import html
import re
from typing import Callable, Dict, List, Optional, Tuple

CONVERTER_VERSION = "1.2.0"

# Inline patterns, applied in this order. Code spans are extracted first and stashed so
# that emphasis and link syntax inside them is never interpreted.
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_ITALIC_STAR_RE = re.compile(r"(?<![\*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?![\*\w])")
_ITALIC_US_RE = re.compile(r"(?<![_\w])_(?=\S)([^_]+?)(?<=\S)_(?![_\w])")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)

_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")
_HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")

# Anything that looks like markdown we do not handle.
_UNSUPPORTED = (
    (re.compile(r"^\s*\[[^\]]+\]:\s+\S+"), "reference-style link definition"),
    (re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+"), "task list item"),
    (re.compile(r"^\s*\[\^[^\]]+\]:"), "footnote definition"),
    (re.compile(r"^=+\s*$"), "setext heading underline"),
)


def escape(text: str) -> str:
    """XML-escape text for storage format. Storage format is XHTML, so & < > all matter."""
    return html.escape(text, quote=False)


def _cdata(text: str) -> str:
    """Wrap in CDATA, splitting any literal ']]>' that would terminate it early."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def code_macro(code: str, language: str = "", title: str = "",
               collapse: bool = False) -> str:
    params = []
    if language:
        params.append('<ac:parameter ac:name="language">{}</ac:parameter>'.format(escape(language)))
    if title:
        params.append('<ac:parameter ac:name="title">{}</ac:parameter>'.format(escape(title)))
    if collapse:
        params.append('<ac:parameter ac:name="collapse">true</ac:parameter>')
    return ('<ac:structured-macro ac:name="code">{}'
            '<ac:plain-text-body>{}</ac:plain-text-body>'
            '</ac:structured-macro>').format("".join(params), _cdata(code))


def page_link(title: str, label: Optional[str] = None) -> str:
    body = ""
    if label and label != title:
        body = "<ac:plain-text-link-body>{}</ac:plain-text-link-body>".format(_cdata(label))
    return ('<ac:link><ri:page ri:content-title="{}"/>{}</ac:link>'
            .format(escape(title), body))


def attachment_image(filename: str, alt: str = "") -> str:
    alt_attr = ' ac:alt="{}"'.format(escape(alt)) if alt else ""
    return ('<ac:image{}><ri:attachment ri:filename="{}"/></ac:image>'
            .format(alt_attr, escape(filename)))


class Converter:
    """Converts one markdown document.

    ``link_resolver`` maps a markdown href to either ``("page", title)`` for an internal
    Confluence page link or ``("url", href)`` for a plain external link. Returning None
    falls back to a plain link. This is what turns ``[user-role.md](user-role.md)`` into a
    real sibling-page link instead of a dead relative URL, and it is why the sync script
    has to create every page before converting any body.

    ``mermaid_handler`` receives ``(code, index)`` and returns the storage snippet to
    emit. The sync script uses it to emit a rendered image plus collapsed source when
    attachment upload succeeded, and just the source when it did not.
    """

    def __init__(self,
                 link_resolver: Optional[Callable[[str], Optional[Tuple[str, str]]]] = None,
                 mermaid_handler: Optional[Callable[[str, int], str]] = None,
                 warn: Optional[Callable[[str], None]] = None):
        self.link_resolver = link_resolver
        self.mermaid_handler = mermaid_handler
        self.warn = warn or (lambda _m: None)
        self._mermaid_index = 0

    # ------------------------------------------------------------------ inline

    def inline(self, text: str) -> str:
        stash: List[str] = []

        def stash_code(m):
            stash.append('<code>{}</code>'.format(escape(m.group(1).strip())))
            return "\x00{}\x00".format(len(stash) - 1)

        text = re.sub(r"`([^`]+)`", stash_code, text)
        text = escape(text)

        def img(m):
            alt, src = m.group(1), m.group(2)
            if src.startswith(("http://", "https://")):
                return ('<ac:image ac:alt="{}"><ri:url ri:value="{}"/></ac:image>'
                        .format(escape(alt), escape(src)))
            # A relative image path cannot be resolved without uploading it as an
            # attachment; say so rather than emitting a link that renders as broken.
            self.warn("relative image {!r} left as a link -- upload it as an attachment "
                      "to render it inline".format(src))
            return '<a href="{}">{}</a>'.format(escape(src), escape(alt or src))

        text = _IMAGE_RE.sub(img, text)

        def link(m):
            label, href = m.group(1), m.group(2)
            resolved = self.link_resolver(href) if self.link_resolver else None
            if resolved and resolved[0] == "page":
                return page_link(resolved[1], label)
            target = resolved[1] if resolved else href
            if target.startswith("#"):
                # Storage format has no portable same-page anchor link; keep the text.
                return escape(label)
            return '<a href="{}">{}</a>'.format(escape(target), escape(label))

        text = _LINK_RE.sub(link, text)
        text = _BOLD_RE.sub(lambda m: "<strong>{}</strong>".format(m.group(1)), text)
        text = _STRIKE_RE.sub(lambda m: "<s>{}</s>".format(m.group(1)), text)
        text = _ITALIC_STAR_RE.sub(lambda m: "<em>{}</em>".format(m.group(1)), text)
        text = _ITALIC_US_RE.sub(lambda m: "<em>{}</em>".format(m.group(1)), text)

        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)

    # ------------------------------------------------------------------- block

    def convert(self, md: str) -> str:
        lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        out: List[str] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]

            if not line.strip():
                i += 1
                continue

            # HTML comments (the managed sync block lives in one) are dropped: the
            # Confluence side gets its own source panel instead.
            if line.lstrip().startswith("<!--"):
                while i < n and "-->" not in lines[i]:
                    i += 1
                i += 1
                continue

            fence = _FENCE_RE.match(line)
            if fence:
                marker, lang = fence.group(1), (fence.group(2) or "").lower()
                i += 1
                buf: List[str] = []
                while i < n and not lines[i].strip().startswith(marker[0] * len(marker)):
                    buf.append(lines[i])
                    i += 1
                i += 1  # closing fence
                code = "\n".join(buf)
                if lang == "mermaid":
                    out.append(self._mermaid(code))
                else:
                    out.append(code_macro(code, lang))
                continue

            heading = _HEADING_RE.match(line)
            if heading:
                level = len(heading.group(1))
                out.append("<h{0}>{1}</h{0}>".format(level, self.inline(heading.group(2))))
                i += 1
                continue

            if _HR_RE.match(line):
                out.append("<hr/>")
                i += 1
                continue

            # Table: a header row followed by a separator row.
            if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
                block, i = self._collect_table(lines, i)
                out.append(block)
                continue

            if _UL_RE.match(line) or _OL_RE.match(line):
                block, i = self._collect_list(lines, i)
                out.append(block)
                continue

            if line.lstrip().startswith(">"):
                buf = []
                while i < n and lines[i].lstrip().startswith(">"):
                    buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                inner = self.convert("\n".join(buf))
                out.append("<blockquote>{}</blockquote>".format(inner))
                continue

            for pat, what in _UNSUPPORTED:
                if pat.match(line):
                    self.warn("unsupported markdown ({}) passed through as text: {!r}"
                              .format(what, line.strip()[:80]))

            # Paragraph: consume until a blank line or the start of another block.
            buf = [line]
            i += 1
            while i < n and lines[i].strip() and not self._starts_block(lines, i):
                buf.append(lines[i])
                i += 1
            out.append("<p>{}</p>".format(self.inline(" ".join(s.strip() for s in buf))))

        return "\n".join(out)

    def _starts_block(self, lines: List[str], i: int) -> bool:
        line = lines[i]
        if _HEADING_RE.match(line) or _FENCE_RE.match(line) or _HR_RE.match(line):
            return True
        if _UL_RE.match(line) or _OL_RE.match(line):
            return True
        if line.lstrip().startswith((">", "<!--")):
            return True
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            return True
        return False

    def _mermaid(self, code: str) -> str:
        self._mermaid_index += 1
        if self.mermaid_handler:
            return self.mermaid_handler(code, self._mermaid_index)
        return code_macro(code, "text", title="Mermaid diagram (source)")

    # -------------------------------------------------------------------- table

    def _collect_table(self, lines: List[str], i: int) -> Tuple[str, int]:
        def cells(row: str) -> List[str]:
            row = row.strip()
            if row.startswith("|"):
                row = row[1:]
            if row.endswith("|"):
                row = row[:-1]
            # GFM: a backslash-escaped pipe is cell content, not a separator.
            # Split only on unescaped ones, then unescape what survives -- so a
            # cell like "`INTERNAL`\|`EXTERNAL`" stays one cell and renders the
            # pipe, instead of spilling into a surplus column.
            out, buf, k = [], [], 0
            while k < len(row):
                ch = row[k]
                if ch == "\\" and k + 1 < len(row) and row[k + 1] == "|":
                    buf.append("|")
                    k += 2
                    continue
                if ch == "|":
                    out.append("".join(buf).strip())
                    buf = []
                    k += 1
                    continue
                buf.append(ch)
                k += 1
            out.append("".join(buf).strip())
            return out

        header = cells(lines[i])
        i += 2  # header + separator
        body_rows: List[List[str]] = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            body_rows.append(cells(lines[i]))
            i += 1

        width = len(header)
        parts = ["<table><tbody><tr>"]
        parts += ["<th>{}</th>".format(self.inline(c)) for c in header]
        parts.append("</tr>")
        for row in body_rows:
            if len(row) > width:
                # Almost always an unescaped '|' inside a cell. Merging the surplus back
                # into the final cell preserves the text; truncating would silently drop
                # it, which is the worse failure for a reference document.
                self.warn("table row has {} cells but header has {} -- likely an "
                          "unescaped '|'; merged the surplus into the last column. "
                          "Row: {!r}".format(len(row), width, " | ".join(row)[:90]))
                row = row[: width - 1] + [" | ".join(row[width - 1:])]
            elif len(row) < width:
                self.warn("table row has {} cells but header has {}; padded with blanks. "
                          "Row: {!r}".format(len(row), width, " | ".join(row)[:90]))
                row = row + [""] * (width - len(row))
            parts.append("<tr>" + "".join(
                "<td>{}</td>".format(self.inline(c)) for c in row) + "</tr>")
        parts.append("</tbody></table>")
        return "".join(parts), i

    # --------------------------------------------------------------------- list

    def _collect_list(self, lines: List[str], i: int) -> Tuple[str, int]:
        """Build a possibly-nested list. Nesting is taken from leading indentation."""
        items: List[Tuple[int, str, str]] = []  # (indent, kind, text)
        while i < len(lines) and lines[i].strip():
            m_ul, m_ol = _UL_RE.match(lines[i]), _OL_RE.match(lines[i])
            if m_ul:
                items.append((len(m_ul.group(1)), "ul", m_ul.group(2)))
            elif m_ol:
                items.append((len(m_ol.group(1)), "ol", m_ol.group(2)))
            else:
                # A continuation line belonging to the previous item.
                if items:
                    ind, kind, text = items[-1]
                    items[-1] = (ind, kind, text + " " + lines[i].strip())
                else:
                    break
            i += 1

        def build(pos: int, indent: int) -> Tuple[str, int]:
            kind = items[pos][1]
            out = ["<{}>".format(kind)]
            while pos < len(items) and items[pos][0] >= indent:
                cur_indent, cur_kind, text = items[pos]
                if cur_indent > indent:
                    nested, pos = build(pos, cur_indent)
                    out[-1] = out[-1][:-len("</li>")] + nested + "</li>"
                    continue
                if cur_kind != kind:
                    break
                out.append("<li>{}</li>".format(self.inline(text)))
                pos += 1
            out.append("</{}>".format(kind))
            return "".join(out), pos

        base_indent = min(it[0] for it in items)
        block, _ = build(0, base_indent)
        return block, i


def convert(md: str, **kw) -> str:
    """Convenience wrapper for a one-shot conversion."""
    return Converter(**kw).convert(md)
