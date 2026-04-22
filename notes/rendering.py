import re

import bleach
import markdown
from bleach.linkifier import Linker


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>",
    flags=re.DOTALL | re.IGNORECASE,
)


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
    return linker.linkify(clean)
