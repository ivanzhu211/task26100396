"""Parser turning JVM stack-trace text into an ExceptionNode tree.

Input guarantees: logcat prefixes already stripped; only standard JVM
exception headers, "at" frames, "Caused by", "Suppressed" and
"... N more" collapse lines; single-line messages; legal, untruncated,
acyclic structure.  One tab and four spaces each mean one indent level
and may be mixed.
"""

from __future__ import annotations

import re

from .model import ExceptionNode
from .seqhash import frame_element_hash

_HEADER_CLASS_RE = re.compile(r"[^\s:]+")
_COLLAPSE_RE = re.compile(r"\.\.\. (\d+) more")


class FrameInterner:
    """Interns (class_name, method_name) pairs to small integer ids."""

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], int] = {}
        self._keys: list[tuple[str, str]] = []
        # Content-based element hash per interned frame id.
        self.element_hashes: list[int] = []

    def intern(self, class_name: str, method_name: str) -> int:
        key = (class_name, method_name)
        frame_id = self._ids.get(key)
        if frame_id is None:
            frame_id = len(self._ids)
            self._ids[key] = frame_id
            self._keys.append(key)
            self.element_hashes.append(frame_element_hash(class_name, method_name))
        return frame_id

    def frame_key(self, frame_id: int) -> tuple[str, str]:
        """Return the (class_name, method_name) for an interned frame id."""
        return self._keys[frame_id]

    def __len__(self) -> int:
        return len(self._ids)


def _indent_level(line: str) -> int:
    level = 0
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "\t":
            level += 1
            index += 1
        elif char == " ":
            start = index
            while index < length and line[index] == " ":
                index += 1
            level += (index - start) // 4
        else:
            break
    return level


def _parse_class_name(header: str) -> str:
    match = _HEADER_CLASS_RE.match(header)
    return match.group(0) if match else ""


def parse_report(text: str, interner: FrameInterner) -> ExceptionNode:
    """Parse one report into the root ExceptionNode."""
    root: ExceptionNode | None = None
    # Stack of (indent_level, node) for currently open exception blocks.
    stack: list[tuple[int, ExceptionNode]] = []

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        level = _indent_level(raw_line)
        line = raw_line.strip()

        if line.startswith("at "):
            while stack and stack[-1][0] >= level:
                stack.pop()
            owner = stack[-1][1]
            ref = line[3:].partition("(")[0]
            class_name, _, method_name = ref.rpartition(".")
            owner.explicit_frames.append(interner.intern(class_name, method_name))
            continue

        collapse = _COLLAPSE_RE.fullmatch(line)
        if collapse is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()
            owner = stack[-1][1]
            owner.collapse_count = int(collapse.group(1))
            continue

        if line.startswith("Caused by: "):
            header = line[len("Caused by: "):]
            while stack and stack[-1][0] > level:
                stack.pop()
            explained = stack[-1][1]
            node = ExceptionNode(class_name=_parse_class_name(header), outer=explained)
            explained.cause = node
            stack[-1] = (level, node)
            continue

        if line.startswith("Suppressed: "):
            header = line[len("Suppressed: "):]
            while stack and stack[-1][0] >= level:
                stack.pop()
            owner = stack[-1][1]
            node = ExceptionNode(class_name=_parse_class_name(header), outer=owner)
            owner.suppressed.append(node)
            stack.append((level, node))
            continue

        # Plain exception header: only legal as the report's first line.
        node = ExceptionNode(class_name=_parse_class_name(line))
        root = node
        stack = [(level, node)]

    if root is None:
        raise ValueError("empty report")
    return root
