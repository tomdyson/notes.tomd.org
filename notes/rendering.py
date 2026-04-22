import re

import bleach
import markdown
from bleach.linkifier import Linker


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>",
    flags=re.DOTALL | re.IGNORECASE,
)

_IMG_OR_ANCHOR_RE = re.compile(
    r"<a\b[^>]*>|</a\s*>|<img\b[^>]*/?>",
    flags=re.IGNORECASE,
)
_IMG_SRC_RE = re.compile(r'''src\s*=\s*"([^"]*)"''', flags=re.IGNORECASE)


ALLOWED_TAGS = [
    "a", "abbr", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "span", "strong",
    "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "ul",
]

ALLOWED_ATTRS = {
    "*": ["id", "class"],
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
    "th": ["align", "colspan", "rowspan"],
    "td": ["align", "colspan", "rowspan"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _set_link_rel(attrs, new=False):
    attrs[(None, "rel")] = "nofollow noopener"
    return attrs


def _wrap_images_in_expand_links(html: str) -> str:
    """Wrap each <img> not already inside an <a> in a click-to-expand link."""
    out = []
    depth = 0
    pos = 0
    for m in _IMG_OR_ANCHOR_RE.finditer(html):
        out.append(html[pos:m.start()])
        token = m.group()
        lower = token.lower()
        if lower.startswith("</a"):
            out.append(token)
            depth = max(0, depth - 1)
        elif lower.startswith("<a"):
            out.append(token)
            depth += 1
        else:  # <img ...>
            if depth > 0:
                out.append(token)
            else:
                src_match = _IMG_SRC_RE.search(token)
                if src_match and src_match.group(1):
                    src = src_match.group(1)
                    out.append(
                        f'<a href="{src}" target="_blank" rel="noopener noreferrer">'
                        f'{token}</a>'
                    )
                else:
                    out.append(token)
        pos = m.end()
    out.append(html[pos:])
    return "".join(out)


def render_markdown(src: str) -> str:
    md = markdown.Markdown(
        extensions=["fenced_code", "codehilite", "tables", "toc", "sane_lists"],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
        },
        output_format="html",
    )
    raw = md.convert(src or "")
    raw = _SCRIPT_STYLE_RE.sub("", raw)
    clean = bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    linker = Linker(callbacks=[_set_link_rel], parse_email=False)
    linked = linker.linkify(clean)
    return _wrap_images_in_expand_links(linked)
