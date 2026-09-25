"""Render Confluence storage format to a browsable HTML approximation.

This is a *preview*, not a renderer: it shows how the page is structured and what the
converter produced, styled roughly like Confluence, so mistakes are visible before
anything is published. Macro rendering is approximated -- the real page is rendered by
Confluence from the same storage XHTML, which is written alongside each preview.
"""

import html
import os
import re
from typing import Dict, List, Tuple

_CSS = """
:root{--fg:#172b4d;--muted:#626f86;--line:#dfe1e6;--bg:#fff;--code-bg:#f4f5f7;
      --info-bg:#deebff;--info-br:#4c9aff;--link:#0c66e4;--chip:#e9f2ff}
@media(prefers-color-scheme:dark){:root{--fg:#c7d1db;--muted:#8c9bab;--line:#2c333a;
      --bg:#1d2125;--code-bg:#22272b;--info-bg:#1c2b41;--info-br:#0055cc;
      --link:#579dff;--chip:#1c2b41}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:15px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1020px;margin:0 auto;padding:28px 22px 90px}
.bar{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
     padding:12px 0;margin-bottom:22px;z-index:5}
.bar h1{font-size:15px;margin:0;font-weight:600}
.bar .sub{color:var(--muted);font-size:12.5px;margin-top:3px}
.page{border:1px solid var(--line);border-radius:6px;margin:0 0 30px;overflow:hidden}
.page>header{background:var(--code-bg);border-bottom:1px solid var(--line);padding:11px 18px}
.page>header .t{font-weight:600;font-size:14px;word-break:break-word}
.page>header .m{color:var(--muted);font-size:12px;margin-top:3px;font-family:ui-monospace,Consolas,monospace}
.body{padding:6px 18px 20px}
h1,h2,h3,h4{line-height:1.3;margin:1.5em 0 .5em;font-weight:600}
h1{font-size:23px}h2{font-size:19px}h3{font-size:16px}h4{font-size:14px}
p{margin:.7em 0}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
code{background:var(--code-bg);padding:1px 5px;border-radius:3px;
     font:13px ui-monospace,Consolas,"Courier New",monospace}
pre{background:var(--code-bg);border:1px solid var(--line);border-radius:4px;
    padding:12px 14px;overflow-x:auto;margin:.8em 0}
pre code{background:none;padding:0;font-size:12.5px;line-height:1.55}
.tw{overflow-x:auto;margin:1em 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--code-bg);font-weight:600}
blockquote{border-left:3px solid var(--line);margin:.9em 0;padding:.1em 0 .1em 14px;color:var(--muted)}
ul,ol{padding-left:24px;margin:.6em 0}li{margin:.22em 0}
hr{border:0;border-top:1px solid var(--line);margin:1.6em 0}
.macro-info{background:var(--info-bg);border-left:3px solid var(--info-br);
            border-radius:3px;padding:11px 14px;margin:1em 0;font-size:13.5px}
.macro-info p{margin:.3em 0}
.pagelink{color:var(--link);border-bottom:1px dotted var(--link)}
.pagelink::before{content:"\\1F4C4\\00a0";opacity:.65;font-size:.9em}
.imgph{display:flex;align-items:center;gap:9px;border:1px dashed var(--info-br);
       border-radius:4px;padding:10px 13px;margin:1em 0;background:var(--chip);font-size:13px}
details{margin:.7em 0;border:1px solid var(--line);border-radius:4px;padding:7px 11px;
        background:var(--code-bg)}
summary{cursor:pointer;font-size:13px;color:var(--muted);font-weight:600}
.note{color:var(--muted);font-size:12.5px;font-style:italic;margin:.5em 0}
"""


def _strip_cdata(text: str) -> str:
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", lambda m: m.group(1), text, flags=re.S)


def storage_to_html(storage: str) -> str:
    """Approximate Confluence rendering of a storage-format fragment."""
    out = storage

    # code macro -> <pre>, honouring the collapse parameter as <details>
    def code_macro(m):
        block = m.group(0)
        lang = re.search(r'ac:name="language">([^<]*)<', block)
        title = re.search(r'ac:name="title">([^<]*)<', block)
        collapse = 'ac:name="collapse">true<' in block
        body = re.search(r"<ac:plain-text-body>(.*?)</ac:plain-text-body>", block, re.S)
        code = html.escape(_strip_cdata(body.group(1))) if body else ""
        pre = "<pre><code>{}</code></pre>".format(code)
        label = title.group(1) if title else (
            "{} snippet".format(lang.group(1)) if lang and lang.group(1) else "Code")
        if collapse:
            return "<details><summary>{}</summary>{}</details>".format(
                html.escape(label), pre)
        return pre

    out = re.sub(r'<ac:structured-macro ac:name="code".*?</ac:structured-macro>',
                 code_macro, out, flags=re.S)

    # info macro
    out = re.sub(
        r'<ac:structured-macro ac:name="info"[^>]*>\s*<ac:rich-text-body>(.*?)'
        r'</ac:rich-text-body>\s*</ac:structured-macro>',
        lambda m: '<div class="macro-info">{}</div>'.format(m.group(1)), out, flags=re.S)

    # any remaining macro -> visible marker, so nothing disappears silently
    out = re.sub(
        r'<ac:structured-macro ac:name="([^"]+)".*?</ac:structured-macro>',
        lambda m: '<div class="note">[{} macro]</div>'.format(html.escape(m.group(1))),
        out, flags=re.S)
    out = re.sub(r'<ac:structured-macro ac:name="([^"]+)"\s*/>',
                 lambda m: '<div class="note">[{} macro]</div>'.format(html.escape(m.group(1))),
                 out)

    # internal page link
    def page_link(m):
        block = m.group(0)
        title = re.search(r'ri:content-title="([^"]*)"', block)
        label = re.search(r"<ac:plain-text-link-body>(.*?)</ac:plain-text-link-body>",
                          block, re.S)
        text = _strip_cdata(label.group(1)) if label else (title.group(1) if title else "page")
        tip = title.group(1) if title else ""
        return '<span class="pagelink" title="Confluence page: {}">{}</span>'.format(
            html.escape(tip), html.escape(text))

    out = re.sub(r"<ac:link>.*?</ac:link>", page_link, out, flags=re.S)

    # images
    out = re.sub(
        r'<ac:image[^>]*>\s*<ri:attachment ri:filename="([^"]*)"\s*/>\s*</ac:image>',
        lambda m: '<div class="imgph">&#128206; attachment <code>{}</code> '
                  '&mdash; rendered on the real page</div>'.format(html.escape(m.group(1))),
        out, flags=re.S)
    out = re.sub(
        r'<ac:image[^>]*>\s*<ri:url ri:value="([^"]*)"\s*/>\s*</ac:image>',
        lambda m: '<div class="imgph">&#127760; external image <code>{}</code></div>'
                  .format(html.escape(m.group(1))), out, flags=re.S)

    out = re.sub(r"<table>", '<div class="tw"><table>', out)
    out = re.sub(r"</table>", "</table></div>", out)
    return out


def render_document(pages: List[Tuple[str, str, str, str]], heading: str,
                    subtitle: str) -> str:
    """pages: list of (title, source_path, status, storage_xhtml)."""
    parts = ['<div class="bar"><h1>{}</h1><div class="sub">{}</div></div>'.format(
        html.escape(heading), html.escape(subtitle))]
    for title, source, status, storage in pages:
        parts.append(
            '<section class="page"><header><div class="t">{}</div>'
            '<div class="m">{} &nbsp;&middot;&nbsp; {}</div></header>'
            '<div class="body">{}</div></section>'.format(
                html.escape(title), html.escape(source or "(generated)"),
                html.escape(status), storage_to_html(storage)))
    return ("<title>{}</title><style>{}</style><div class=\"wrap\">{}</div>"
            .format(html.escape(heading), _CSS, "".join(parts)))


def write_preview(out_dir: str, pages: List[Tuple[str, str, str, str]],
                  heading: str, subtitle: str) -> Dict[str, str]:
    """Write one combined HTML preview plus the raw storage for each page."""
    os.makedirs(out_dir, exist_ok=True)
    written = {}
    for title, _src, _status, storage in pages:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", title)[:120]
        path = os.path.join(out_dir, safe + ".storage.xhtml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(storage)
        written[title] = path
    index = os.path.join(out_dir, "preview.html")
    with open(index, "w", encoding="utf-8") as fh:
        fh.write(render_document(pages, heading, subtitle))
    written["__index__"] = index
    return written
