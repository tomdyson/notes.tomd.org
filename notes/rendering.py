import re
from html import escape

import bleach
import markdown
from bleach.linkifier import Linker


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>",
    flags=re.DOTALL | re.IGNORECASE,
)
_MERMAID_FENCE_RE = re.compile(
    r"^```mermaid[^\n]*\r?\n(?P<body>.*?)(?:\r?\n```[ \t]*(?:\r?\n|$))",
    flags=re.DOTALL | re.MULTILINE,
)

_IMG_OR_ANCHOR_RE = re.compile(
    r"<a\b[^>]*>|</a\s*>|<img\b[^>]*/?>",
    flags=re.IGNORECASE,
)
_IMG_SRC_RE = re.compile(r'''src\s*=\s*"([^"]*)"''', flags=re.IGNORECASE)

_TASK_LI_RE = re.compile(
    r'<li>(?P<lead>\s*(?:<p>\s*)?)\[(?P<state>[ xX])\]\s+',
)
_TASK_LINE_RE = re.compile(
    r'^([ \t]*[-*+][ \t]+)(\[[ xX]\])(\s)',
    flags=re.MULTILINE,
)
_FENCE_LINE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
_LIST_INTERRUPT_RE = re.compile(r"^[ ]{0,3}[-*+][ \t]+")


ALLOWED_TAGS = [
    "a", "abbr", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "input", "li", "ol", "p", "pre", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "ul",
]

ALLOWED_ATTRS = {
    "*": ["id", "class"],
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
    "input": ["type", "checked", "disabled", "data-task-index"],
    "li": ["id", "class"],
    "th": ["align", "colspan", "rowspan"],
    "td": ["align", "colspan", "rowspan"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _set_link_rel(attrs, new=False):
    attrs[(None, "rel")] = "nofollow noopener"
    return attrs


def _replace_mermaid_fence(match):
    body = match.group("body").rstrip()
    return f'\n<div class="mermaid">{escape(body)}</div>\n'


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


def _replace_task_list_items(html: str) -> str:
    counter = [0]

    def sub(m):
        idx = counter[0]
        counter[0] += 1
        checked = m.group("state").lower() == "x"
        attrs = ' checked' if checked else ''
        return (
            f'<li class="task-item">{m.group("lead")}'
            f'<input type="checkbox" disabled data-task-index="{idx}"{attrs}> '
        )

    return _TASK_LI_RE.sub(sub, html)


def _allow_marked_list_interruptions(src: str) -> str:
    """Let server rendering match Marked when a paragraph is followed by a list."""
    out = []
    previous = ""
    fence = None

    for line in src.splitlines(keepends=True):
        stripped_line = line.rstrip("\r\n")
        fence_match = _FENCE_LINE_RE.match(stripped_line)

        if fence:
            out.append(line)
            if fence_match:
                marker = fence_match.group(1)
                if marker[0] == fence[0] and len(marker) >= fence[1]:
                    fence = None
            previous = stripped_line
            continue

        if fence_match:
            marker = fence_match.group(1)
            fence = (marker[0], len(marker))
        elif (
            previous.strip()
            and not _LIST_INTERRUPT_RE.match(previous)
            and _LIST_INTERRUPT_RE.match(stripped_line)
        ):
            out.append("\r\n" if line.endswith("\r\n") else "\n")

        out.append(line)
        previous = stripped_line

    return "".join(out)


def toggle_task_in_markdown(src: str, index: int):
    """Flip the Nth task checkbox in the markdown source.

    Returns the new markdown, or None if there is no task at that index.
    Indexing matches the order in which task <li>s are rendered, which is
    the source order of lines matching ``[-*+] [ ]`` / ``[-*+] [x]``.
    """
    if index < 0:
        return None
    matches = list(_TASK_LINE_RE.finditer(src or ""))
    if index >= len(matches):
        return None
    m = matches[index]
    bracket = m.group(2)
    new_bracket = "[ ]" if bracket[1].lower() == "x" else "[x]"
    return src[: m.start(2)] + new_bracket + src[m.end(2) :]


def render_markdown(src: str) -> str:
    src = _MERMAID_FENCE_RE.sub(_replace_mermaid_fence, src or "")
    src = _allow_marked_list_interruptions(src)
    md = markdown.Markdown(
        extensions=["fenced_code", "codehilite", "tables", "toc", "sane_lists"],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
        },
        output_format="html",
    )
    raw = md.convert(src)
    raw = _SCRIPT_STYLE_RE.sub("", raw)
    raw = _replace_task_list_items(raw)
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
