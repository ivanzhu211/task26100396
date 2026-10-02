"""Data model for parsed crash reports.

An ExceptionNode mirrors one JVM exception block: its class name, the
explicitly printed frames, an optional collapsed-tail reference
("... N more"), an optional direct cause, and the suppressed exceptions
it directly owns.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExceptionNode:
    """One exception block inside a crash report."""

    class_name: str
    # Explicitly printed frames, each an interned frame id (int).
    explicit_frames: list[int] = field(default_factory=list)
    # Direct outer exception used by the collapsed-tail line, or None.
    outer: "ExceptionNode | None" = None
    # N of the "... N more" line; None when the block has no collapsed tail.
    collapse_count: "int | None" = None
    # Direct cause ("Caused by"), or None.
    cause: "ExceptionNode | None" = None
    # Directly owned suppressed exceptions, in textual order.
    suppressed: list["ExceptionNode"] = field(default_factory=list)
