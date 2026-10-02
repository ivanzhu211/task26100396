"""Structural fingerprinting of a parsed exception tree.

Two reports group together iff their normalised exception structures are
identical: same exception classes, same full frame sequences (order and
repetition included), same cause relations, and equal multisets of
directly owned suppressed exceptions at every nesting level.  Suppressed
order is normalised by sorting child digests before combining.

All traversal is iterative so 20k-deep cause chains cannot overflow the
Python call stack.
"""

from __future__ import annotations

import hashlib

from .model import ExceptionNode
from .seqhash import compute_sequence_hashes

_DIGEST_SIZE = 16


def fingerprint_tree(
    root: ExceptionNode,
    element_hashes: list[int],
    seq_hashes: dict[int, tuple[int, int]] | None = None,
) -> bytes:
    """Return a stable digest of the normalised exception structure."""
    if seq_hashes is None:
        seq_hashes = compute_sequence_hashes(root, element_hashes)

    digests: dict[int, bytes] = {}
    # Iterative post-order: each stack entry is (node, children_expanded).
    stack: list[tuple[ExceptionNode, bool]] = [(root, False)]
    while stack:
        node, expanded = stack.pop()
        if not expanded:
            stack.append((node, True))
            if node.cause is not None:
                stack.append((node.cause, False))
            for child in node.suppressed:
                stack.append((child, False))
            continue
        seq_hash, seq_len = seq_hashes[id(node)]
        hasher = hashlib.blake2b(digest_size=_DIGEST_SIZE)
        hasher.update(b"E")
        name = node.class_name.encode("utf-8")
        hasher.update(len(name).to_bytes(4, "big"))
        hasher.update(name)
        hasher.update(seq_hash.to_bytes(8, "big"))
        hasher.update(seq_len.to_bytes(8, "big"))
        if node.cause is not None:
            hasher.update(b"C")
            hasher.update(digests[id(node.cause)])
        else:
            hasher.update(b"c")
        child_digests = sorted(digests[id(child)] for child in node.suppressed)
        hasher.update(len(child_digests).to_bytes(4, "big"))
        for child_digest in child_digests:
            hasher.update(child_digest)
        digests[id(node)] = hasher.digest()
    return digests[id(root)]
