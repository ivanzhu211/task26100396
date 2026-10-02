"""Group reports by their crash-semantics fingerprint."""

from __future__ import annotations

from typing import Any, Iterable

from .fingerprint import fingerprint
from .parser import parse_report


def fingerprint_report(text: str) -> str:
    """Stable fingerprint for a single report.

    Depends only on crash semantics (exception classes, full frame
    sequences, cause links, suppressed multisets); identical across
    processes, batches and input order.
    """
    return fingerprint(parse_report(text))


def group_reports(reports: Iterable[tuple[Any, str]]) -> list[list[Any]]:
    """Group ``(report_id, text)`` pairs; return groups of report ids.

    Group order follows first appearance of each group in the input;
    ids within a group keep input order.
    """
    groups: dict[str, list[Any]] = {}
    for report_id, text in reports:
        key = fingerprint_report(text)
        bucket = groups.get(key)
        if bucket is None:
            groups[key] = [report_id]
        else:
            bucket.append(report_id)
    return list(groups.values())
