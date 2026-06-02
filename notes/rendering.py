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
_LIST_ITEM_RE = re.compile(
    r"^(?P<indent> *)(?P<marker>[-*+]|\d{1,9}[.)])(?P<after> +)(?P<rest>.*)$"
)
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([-*_])( *\1){2,} *$")


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


def _is_list_item(line: str) -> bool:
    """True for a list-marker line at any indentation (ordered or unordered)."""
    return bool(_LIST_ITEM_RE.match(line)) and not _THEMATIC_BREAK_RE.match(line)


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
            and not _is_list_item(previous)
            and _LIST_INTERRUPT_RE.match(stripped_line)
        ):
            out.append("\r\n" if line.endswith("\r\n") else "\n")

        out.append(line)
        previous = stripped_line

    return "".join(out)


def _normalize_list_indentation(src: str) -> str:
    """Re-indent nested list items so Python-Markdown nests like marked.

    marked (the live preview) follows CommonMark: a sub-item nests whenever it
    is indented past its parent's *content* column — two spaces (the width of
    "- ") is enough, and indenting further than that does not add extra levels.
    Python-Markdown instead nests on a fixed ``tab_length`` of four, so the same
    source rendered flat in the published HTML and diverged from the preview.

    This pass walks the source, computes each list item's nesting depth using
    marked's relative-indentation rule, and re-emits markers at ``depth * 4``
    spaces — the indentation Python-Markdown expects — so both renderers agree.
    Continuation lines (wrapped text, extra paragraphs inside an item) are
    shifted by the same amount as the item they belong to. Content inside fenced
    code blocks is left untouched.

    Known limits (all rare in practice): fenced blocks *inside* a list item and
    unindented lazy text between list items are passed through unchanged.
    """
    levels = []  # stack of {"src_marker", "src_content", "norm_content"}, deep last
    fence = None
    out = []

    for line in src.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        nl = line[len(content):]
        fence_match = _FENCE_LINE_RE.match(content)

        if fence is not None:
            out.append(line)
            if fence_match:
                marker = fence_match.group(1)
                if marker[0] == fence[0] and len(marker) >= fence[1]:
                    fence = None
            continue
        if fence_match:
            marker = fence_match.group(1)
            fence = (marker[0], len(marker))
            out.append(line)
            continue

        if not content.strip():
            # Blank line: keep any open list open; the next line decides.
            out.append(line)
            continue

        item = _LIST_ITEM_RE.match(content)
        if item and not _THEMATIC_BREAK_RE.match(content):
            ind = len(item.group("indent"))
            marker = item.group("marker")
            rest = item.group("rest")
            while levels and ind < levels[-1]["src_marker"]:
                levels.pop()
            if levels and ind >= levels[-1]["src_content"]:
                depth = len(levels)  # child: one level deeper
                levels.append({"src_marker": ind})
            elif levels and levels[-1]["src_marker"] <= ind:
                depth = len(levels) - 1  # sibling of current level
                levels[-1]["src_marker"] = ind
            else:
                levels = [{"src_marker": ind}]
                depth = 0
            new_indent = depth * 4
            top = levels[-1]
            top["src_content"] = ind + len(marker) + len(item.group("after"))
            # Python-Markdown's content column for a list item at depth d is
            # (d + 1) * tab_length, regardless of marker width — continuations
            # must reach it to stay inside the item.
            top["norm_content"] = (depth + 1) * 4
            out.append(f"{' ' * new_indent}{marker} {rest}{nl}")
            continue

        # Continuation line (not a list item): attach it to the deepest open
        # item whose content column it reaches, shifting it by the same delta.
        ind = len(content) - len(content.lstrip(" "))
        target = -1
        for i, lvl in enumerate(levels):
            if ind >= lvl["src_content"]:
                target = i
        if target >= 0:
            del levels[target + 1:]
            lvl = levels[target]
            norm_ind = lvl["norm_content"] + (ind - lvl["src_content"])
            out.append(f"{' ' * norm_ind}{content.lstrip(' ')}{nl}")
        else:
            levels = []
            out.append(line)

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
    src = _normalize_list_indentation(src)
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
