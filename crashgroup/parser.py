"""Parse normalized JVM crash reports into an exception tree.

Input format (already stripped of logcat prefixes):

- Exception header: ``<class>[: message]``, optionally prefixed by
  ``Caused by: `` or ``Suppressed: ``.
- Frame line: ``at <class>.<method>(<location>)``.
- Collapsed tail line: ``... N more``.

Indentation: one tab or four spaces per level, mixable. Frames and
collapse lines sit one level below their exception header. ``Caused by``
sits at the same level as the exception it explains; ``Suppressed`` sits
one level below its owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_CAUSED_BY = "Caused by: "
_SUPPRESSED = "Suppressed: "
_AT = "at "


@dataclass
class ExceptionNode:
    """One exception in a report.

    ``frames`` holds the explicitly printed ``Class.method`` strings.
    ``collapsed`` is the N from a trailing ``... N more`` line (0 if none).
    ``parent`` is the direct outer exception used to resolve collapsed
    frames: the exception that caused this one, or the one owning it as a
    suppressed exception. ``cause`` and ``suppressed`` are child nodes.
    """

    class_name: str
    frames: list[str] = field(default_factory=list)
    collapsed: int = 0
    parent: "ExceptionNode | None" = None
    cause: "ExceptionNode | None" = None
    suppressed: list["ExceptionNode"] = field(default_factory=list)


def _indent_level(line: str) -> tuple[int, str]:
    """Split leading whitespace into (level, rest). Tab or 4 spaces = 1."""
    level = 0
    spaces = 0
    idx = 0
    for ch in line:
        if ch == "\t":
            level += 1 + spaces // 4
            spaces = 0
        elif ch == " ":
            spaces += 1
            if spaces == 4:
                level += 1
                spaces = 0
        else:
            break
        idx += 1
    return level, line[idx:]


def _parse_class_name(header: str) -> str:
    """Class name is everything before the first ': ' message separator."""
    sep = header.find(":")
    if sep == -1:
        return header
    return header[:sep]


def parse_report(text: str) -> ExceptionNode:
    """Parse report text into the root ``ExceptionNode``."""
    root: ExceptionNode | None = None
    # current[level] = most recently opened exception header at that level.
    current: dict[int, ExceptionNode] = {}

    for line in text.splitlines():
        if not line.strip():
            continue
        level, body = _indent_level(line)

        if body.startswith(_AT):
            node = current[level - 1]
            paren = body.rfind("(")
            node.frames.append(body[len(_AT):paren])
        elif body.startswith("...") and body.endswith(" more"):
            node = current[level - 1]
            node.collapsed = int(body[4:-5])
        elif body.startswith(_CAUSED_BY):
            explained = current[level]
            node = ExceptionNode(
                class_name=_parse_class_name(body[len(_CAUSED_BY):]),
                parent=explained,
            )
            explained.cause = node
            current[level] = node
        elif body.startswith(_SUPPRESSED):
            owner = current[level - 1]
            node = ExceptionNode(
                class_name=_parse_class_name(body[len(_SUPPRESSED):]),
                parent=owner,
            )
            owner.suppressed.append(node)
            current[level] = node
        else:
            node = ExceptionNode(class_name=_parse_class_name(body))
            current[level] = node
            if root is None:
                root = node

    if root is None:
        raise ValueError("empty report")
    return root
