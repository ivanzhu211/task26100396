"""Compute stable fingerprints for parsed exception trees.

Each exception's full frame sequence is ``explicit frames ++ tail N of the
direct outer exception's full sequence``. Sequences are compared via a
polynomial rolling hash modulo a 127-bit prime, so collapsed tails are
resolved symbolically and never expanded, even when a report logically
contains ~1e9 frames.

``tail_query(v, N)`` (hash of the last N frames of v's full sequence) is
answered with binary lifting over the parent chain: while ``N <= c_v``
the tail of v equals the tail of its parent, so we jump to the highest
ancestor whose chain nodes all have ``collapsed >= N`` in O(log depth).
"""

from __future__ import annotations

from hashlib import blake2b

from .parser import ExceptionNode

_MOD = (1 << 127) - 1
_BASE = 0x9E3779B97F4A7C159E3779B97F4A7C15 | 1


def _frame_hash(frame: str, cache: dict[str, int]) -> int:
    h = cache.get(frame)
    if h is None:
        h = int.from_bytes(blake2b(frame.encode(), digest_size=16).digest(), "big") % _MOD
        cache[frame] = h
    return h


def _tail_query(node: ExceptionNode, count: int) -> int:
    """Hash of the last ``count`` frames of node's full frame sequence."""
    v = node
    up = v._up
    mn = v._mn
    for i in range(len(up) - 1, -1, -1):
        if i < len(up) and up[i] is not None and mn[i] >= count:
            v = up[i]
            up = v._up
            mn = v._mn
    c = v.collapsed
    m = count - c
    pfx = v._pfx
    k = len(pfx) - 1
    suffix = (pfx[k] - pfx[k - m] * pow(_BASE, m, _MOD)) % _MOD
    return (suffix * pow(_BASE, c, _MOD) + v._tail_hash) % _MOD


def _compute_sequence_hashes(root: ExceptionNode) -> None:
    """Annotate every node with _pfx, _len, _hash, _tail_hash, _up, _mn."""
    frame_cache: dict[str, int] = {}
    stack: list[tuple[ExceptionNode, int, int]] = [(root, 0, 0)]
    while stack:
        node, depth, _ = stack.pop()

        pfx = [0]
        h = 0
        for frame in node.frames:
            h = (h * _BASE + _frame_hash(frame, frame_cache)) % _MOD
            pfx.append(h)
        node._pfx = pfx

        parent = node.parent
        node._depth = depth
        if parent is None:
            node._up = []
            node._mn = []
            node._tail_hash = 0
        else:
            levels = max(1, depth.bit_length())
            up: list[ExceptionNode | None] = [parent]
            mn: list[int] = [node.collapsed]
            for i in range(1, levels):
                mid = up[i - 1]
                if mid is None:
                    up.append(None)
                    mn.append(mn[i - 1])
                else:
                    up.append(mid._up[i - 1] if i - 1 < len(mid._up) else None)
                    mn.append(min(mn[i - 1], mid._mn[i - 1]))
            node._up = up
            node._mn = mn
            node._tail_hash = (
                _tail_query(parent, node.collapsed) if node.collapsed else 0
            )

        c = node.collapsed
        node._len = len(node.frames) + c
        node._hash = (pfx[-1] * pow(_BASE, c, _MOD) + node._tail_hash) % _MOD

        if node.cause is not None:
            stack.append((node.cause, depth + 1, 0))
        for child in node.suppressed:
            stack.append((child, depth + 1, 0))


def _structural_key(node: ExceptionNode) -> bytes:
    """Order-insensitive (for suppressed) canonical hash of the subtree."""
    # Iterative post-order to survive 20k-deep chains.
    keys: dict[int, bytes] = {}
    stack: list[tuple[ExceptionNode, bool]] = [(node, False)]
    while stack:
        cur, expanded = stack.pop()
        if expanded:
            cause_key = keys.pop(id(cur.cause)) if cur.cause is not None else b"\x00" * 16
            sup_keys = sorted(keys.pop(id(ch)) for ch in cur.suppressed)
            h = blake2b(digest_size=16)
            h.update(b"CLS")
            h.update(cur.class_name.encode())
            h.update(b"LEN")
            h.update(cur._len.to_bytes(16, "big"))
            h.update(b"HSH")
            h.update(cur._hash.to_bytes(16, "big"))
            h.update(b"CAU")
            h.update(cause_key)
            h.update(b"SUP")
            for sk in sup_keys:
                h.update(sk)
            keys[id(cur)] = h.digest()
        else:
            stack.append((cur, True))
            if cur.cause is not None:
                stack.append((cur.cause, False))
            for child in cur.suppressed:
                stack.append((child, False))
    return keys[id(node)]


def fingerprint(root: ExceptionNode) -> str:
    """Return a deterministic fingerprint string for an exception tree."""
    _compute_sequence_hashes(root)
    return _structural_key(root).hex()
