"""Line-preserving text extraction for HTML sections, shared by the crawler providers' detail parsers."""

from __future__ import annotations

import re

from bs4 import Tag

from catalog_core.normalize import clean_text

_WHITESPACE = re.compile(r"\s+")
# Elements whose boundaries start/end a line of text. Inline elements (strong, a, span, em) do not.
_BLOCK_TAGS = frozenset({"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "section", "blockquote"})


def text_with_line_breaks(node: Tag) -> str | None:
    """Text of a section with line breaks only at ``<br>`` and block boundaries.

    Inline elements (strong, a, span, em) never split a line, so ``<strong>2026</strong><strong>國際
    布克獎得主</strong>`` stays on one line. Runs of blank lines collapse to a single blank line.

    **Mutates ``node`` in place** (collapses whitespace inside its strings, replaces ``<br>`` with a newline and
    inserts newlines around block tags). Pass a node that belongs to a soup the caller owns and does not reuse.
    """
    # Source-file whitespace (including CRLF inside the HTML) is not a line break: collapse it first,
    # then add the line breaks that the page structure defines.
    for text in node.find_all(string=True):
        collapsed = _WHITESPACE.sub(" ", str(text))
        if collapsed != str(text):
            text.replace_with(collapsed)
    for tag in node.find_all(True):
        if tag.name == "br":
            tag.replace_with("\n")
        elif tag.name in _BLOCK_TAGS:
            tag.insert_before("\n")
            tag.insert_after("\n")
    lines: list[str] = []
    for raw_line in node.get_text().split("\n"):
        line = clean_text(raw_line) or ""
        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) or None
