"""Android crash-stack grouping library for ResilienceForge analytics.

Pure in-process API: reports go in as strings, fingerprints and groups
come out; nothing touches disk, network, or external services.
"""

from __future__ import annotations

from .model import ExceptionNode
from .parser import FrameInterner, parse_report
from .seqhash import compute_sequence_hashes
from .structure import fingerprint_tree

__all__ = ["fingerprint", "group_reports"]


def fingerprint(report: str) -> str:
    """Stable hex fingerprint of one report's normalised crash semantics."""
    interner = FrameInterner()
    root = parse_report(report, interner)
    return fingerprint_tree(root, interner.element_hashes).hex()


def group_reports(reports: list[str]) -> list[list[int]]:
    """Group report indices by identical normalised crash semantics.

    Returns groups of original report indices; groups are ordered by
    first occurrence and indices inside each group are ascending, so the
    result does not depend on batching or call history.
    """
    groups: dict[bytes, list[int]] = {}
    for index, report in enumerate(reports):
        interner = FrameInterner()
        root = parse_report(report, interner)
        digest = fingerprint_tree(root, interner.element_hashes)
        groups.setdefault(digest, []).append(index)
    return list(groups.values())
