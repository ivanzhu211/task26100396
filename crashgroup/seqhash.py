"""Hashing of full frame sequences without materialising collapsed tails.

Each exception's full frame sequence is its explicit frames followed by
the last N frames of its direct outer exception's full sequence.  Full
sequences may reach a billion frames, so only rolling hashes and lengths
are ever computed, never the frames themselves.

Algorithm: for every node with a collapsed tail we need
suffix(outer(node), N).  Walking the outer chain per query is O(depth)
each and O(depth^2) overall, so queries are instead answered in one
sweep sorted by descending N with a union-find over the outer chains:
a node Y on the chain is transparent for threshold n exactly while
N(Y) >= n, so as the threshold drops each node is unioned to its outer
exactly once, giving near-linear total work.
"""

from __future__ import annotations

import hashlib

from .model import ExceptionNode

_MOD = (1 << 61) - 1
_BASE = 0x9E3779B97F4A7C3


def frame_element_hash(class_name: str, method_name: str) -> int:
    """Content-based per-frame element hash in [1, _MOD).

    Depends only on the class/method text, never on encounter order, so
    fingerprints are stable across processes, batches and input orders.
    """
    data = class_name.encode("utf-8") + b"\x00" + method_name.encode("utf-8")
    raw = int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")
    return raw % (_MOD - 1) + 1


def _collect_nodes(root: ExceptionNode) -> list[ExceptionNode]:
    nodes: list[ExceptionNode] = []
    stack = [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        if node.cause is not None:
            stack.append(node.cause)
        stack.extend(node.suppressed)
    return nodes


def compute_sequence_hashes(
    root: ExceptionNode,
    element_hashes: list[int],
) -> dict[int, tuple[int, int]]:
    """Return {id(node): (sequence_hash, sequence_length)} for all nodes.

    element_hashes maps an interned frame id to its content-based
    element hash (see frame_element_hash).
    """
    nodes = _collect_nodes(root)

    # Prefix hashes of each node's explicit frames.
    prefix: dict[int, list[int]] = {}
    for node in nodes:
        pref = [0]
        acc = 0
        for frame_id in node.explicit_frames:
            acc = (acc * _BASE + element_hashes[frame_id]) % _MOD
            pref.append(acc)
        prefix[id(node)] = pref

    def explicit_suffix_hash(node: ExceptionNode, count: int) -> int:
        pref = prefix[id(node)]
        return (pref[-1] - pref[-1 - count] * pow(_BASE, count, _MOD)) % _MOD

    collapsed = [n for n in nodes if n.collapse_count is not None]

    # Union-find over outer chains; find(x) = nearest ancestor (inclusive)
    # not yet skipped for the current threshold.
    uf: dict[int, int] = {id(n): id(n) for n in nodes}
    node_by_id = {id(n): n for n in nodes}

    def find(nid: int) -> int:
        root_id = nid
        while uf[root_id] != root_id:
            root_id = uf[root_id]
        while uf[nid] != nid:
            uf[nid], nid = root_id, uf[nid]
        return root_id

    # Pass 1 (descending N): find each query's landing node -- the nearest
    # outer-chain ancestor whose explicit frames contribute to the answer.
    skip_order = sorted(collapsed, key=lambda n: n.collapse_count, reverse=True)
    landing_of: dict[int, ExceptionNode] = {}
    skip_pos = 0
    for query in skip_order:
        threshold = query.collapse_count
        while skip_pos < len(skip_order) and skip_order[skip_pos].collapse_count >= threshold:
            node = skip_order[skip_pos]
            uf[id(node)] = find(id(node.outer))
            skip_pos += 1
        landing_of[id(query)] = node_by_id[find(id(query.outer))]

    # Pass 2 (ascending N): a query's answer reuses the tail hash of its
    # landing node, whose collapse count is strictly smaller, so ascending
    # order guarantees dependencies are ready.
    tail_hash: dict[int, int] = {}
    for query in sorted(collapsed, key=lambda n: n.collapse_count):
        threshold = query.collapse_count
        landing = landing_of[id(query)]
        landing_count = landing.collapse_count
        if landing_count is None:
            tail_hash[id(query)] = explicit_suffix_hash(landing, threshold)
        else:
            head = explicit_suffix_hash(landing, threshold - landing_count)
            tail = tail_hash[id(landing)]
            tail_hash[id(query)] = (head * pow(_BASE, landing_count, _MOD) + tail) % _MOD

    result: dict[int, tuple[int, int]] = {}
    for node in nodes:
        pref = prefix[id(node)]
        explicit_len = len(node.explicit_frames)
        if node.collapse_count is None:
            result[id(node)] = (pref[-1], explicit_len)
        else:
            count = node.collapse_count
            full = (pref[-1] * pow(_BASE, count, _MOD) + tail_hash[id(node)]) % _MOD
            result[id(node)] = (full, explicit_len + count)
    return result
