"""Acceptance and property tests for the crashgroup library."""

from __future__ import annotations

import random

from crashgroup import fingerprint, group_reports
from crashgroup.model import ExceptionNode
from crashgroup.parser import FrameInterner, parse_report

# ---------------------------------------------------------------------------
# Reference implementation: full expansion + canonical normalised form.
# Only usable on small inputs; the library must agree with it everywhere.
# ---------------------------------------------------------------------------


def _expand(node: ExceptionNode, memo: dict[int, list[int]]) -> list[int]:
    if id(node) in memo:
        return memo[id(node)]
    seq = list(node.explicit_frames)
    if node.collapse_count is not None:
        outer = _expand(node.outer, memo)
        seq += outer[len(outer) - node.collapse_count:]
    memo[id(node)] = seq
    return seq


def _canonical(node: ExceptionNode, interner: FrameInterner, memo):
    frames = tuple(interner.frame_key(f) for f in _expand(node, memo))
    cause = _canonical(node.cause, interner, memo) if node.cause else None
    sup = tuple(sorted(_canonical(s, interner, memo) for s in node.suppressed))
    return (node.class_name, frames, cause, sup)


def reference_key(report: str):
    interner = FrameInterner()
    root = parse_report(report, interner)
    return _canonical(root, interner, {})


# ---------------------------------------------------------------------------
# Random report generator with noisy but semantics-preserving text choices.
# ---------------------------------------------------------------------------

_CLASSES = [
    "com.a.AppException",
    "com.b.DataException",
    "com.c.NetException",
    "com.d.WrapperException",
]
_FRAMES = [
    ("com.a.A", "run"),
    ("com.a.B", "go"),
    ("com.b.C", "handle"),
    ("com.b.D", "call"),
    ("com.c.E", "exec"),
    ("com.a.A$1", "run"),
    ("com.a.A", "lambda$go$0"),
    ("com.a.A", "<init>"),
]


def _gen_tree(rng: random.Random, interner: FrameInterner) -> ExceptionNode:
    root = ExceptionNode(rng.choice(_CLASSES))
    nodes = [root]
    for _ in range(rng.randint(0, 6)):
        parent = rng.choice(nodes)
        node = ExceptionNode(rng.choice(_CLASSES), outer=parent)
        if parent.cause is None and rng.random() < 0.5:
            parent.cause = node
        else:
            parent.suppressed.append(node)
        nodes.append(node)
    for node in nodes:
        node.explicit_frames = [
            interner.intern(*rng.choice(_FRAMES))
            for _ in range(rng.randint(0, 4))
        ]
    # Assign legal collapse counts bottom-up over the outer chains.
    memo: dict[int, list[int]] = {}
    for node in nodes:
        _expand(node, memo)
        if node.outer is not None and rng.random() < 0.6:
            node.collapse_count = rng.randint(0, len(_expand(node.outer, memo)))
            memo.pop(id(node), None)
            _expand(node, memo)
    return root


def _serialize(root: ExceptionNode, rng: random.Random, interner: FrameInterner) -> str:
    memo: dict[int, list[int]] = {}
    lines: list[str] = []

    def indent(level: int) -> str:
        return "".join(rng.choice(["\t", "    "]) for _ in range(level))

    def frame_line(level: int, frame_id: int) -> str:
        cls, mth = interner.frame_key(frame_id)
        loc = rng.choice(
            [f"X.java:{rng.randint(1, 999)}", "Native Method", "Unknown Source"]
        )
        return f"{indent(level)}at {cls}.{mth}({loc})"

    def header(node: ExceptionNode) -> str:
        if rng.random() < 0.7:
            return f"{node.class_name}: msg{rng.randint(0, 10**6)}"
        return node.class_name

    def emit(node: ExceptionNode, level: int, prefix: str) -> None:
        lines.append(f"{indent(level)}{prefix}{header(node)}")
        for frame_id in node.explicit_frames:
            lines.append(frame_line(level + 1, frame_id))
        if node.collapse_count is not None:
            if rng.random() < 0.5:
                lines.append(f"{indent(level + 1)}... {node.collapse_count} more")
            else:
                full = _expand(node, memo)
                for frame_id in full[len(node.explicit_frames):]:
                    lines.append(frame_line(level + 1, frame_id))
        for child in rng.sample(node.suppressed, len(node.suppressed)):
            emit(child, level + 1, "Suppressed: ")
        if node.cause is not None:
            emit(node.cause, level, "Caused by: ")

    emit(root, 0, "")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Property test: library grouping must equal reference grouping.
# ---------------------------------------------------------------------------


def _partition(keys: list) -> set[frozenset[int]]:
    groups: dict[object, set[int]] = {}
    for index, key in enumerate(keys):
        groups.setdefault(key, set()).add(index)
    return {frozenset(g) for g in groups.values()}


def test_grouping_matches_full_expansion_reference():
    rng = random.Random(20261003)
    reports = []
    references = []
    for _ in range(400):
        interner = FrameInterner()
        tree = _gen_tree(rng, interner)
        text = _serialize(tree, rng, interner)
        reports.append(text)
        references.append(_canonical(tree, interner, {}))
    library_keys = [fingerprint(r) for r in reports]
    assert _partition(library_keys) == _partition(references)
    grouped = {frozenset(g) for g in group_reports(reports)}
    assert grouped == _partition(references)


def test_fingerprint_stable_across_calls_and_order():
    rng = random.Random(7)
    interner = FrameInterner()
    text = _serialize(_gen_tree(rng, interner), rng, interner)
    first = fingerprint(text)
    for _ in range(5):
        assert fingerprint(text) == first
    # Fingerprint of one report must not depend on other reports in a batch.
    assert group_reports([text, text, text]) == [[0, 1, 2]]


# ---------------------------------------------------------------------------
# Acceptance scenarios.
# ---------------------------------------------------------------------------

BASE = """com.example.TopException: boom
\tat com.example.A.run(A.java:10)
\tat com.example.B.go(B.java:20)
\tSuppressed: com.example.SupOne: s1
\t\tat com.example.C.work(C.java:30)
\tSuppressed: com.example.SupTwo: s2
\t\tat com.example.D.deep(D.java:40)
Caused by: com.example.RootCause: why
\tat com.example.E.e(E.java:50)
\t... 2 more
"""


def test_message_and_location_ignored():
    variant = """com.example.TopException: another message entirely
\tat com.example.A.run(A.java:999)
\tat com.example.B.go(Native Method)
\tSuppressed: com.example.SupOne
\t\tat com.example.C.work(Unknown Source)
\tSuppressed: com.example.SupTwo: different
\t\tat com.example.D.deep(D.java:1)
Caused by: com.example.RootCause
\tat com.example.E.e(E.java:50)
\t... 2 more
"""
    assert fingerprint(variant) == fingerprint(BASE)


def test_suppressed_order_insensitive_at_all_levels():
    variant = """com.example.TopException: boom
\tat com.example.A.run(A.java:10)
\tat com.example.B.go(B.java:20)
\tSuppressed: com.example.SupTwo: s2
\t\tat com.example.D.deep(D.java:40)
\tSuppressed: com.example.SupOne: s1
\t\tat com.example.C.work(C.java:30)
Caused by: com.example.RootCause: why
\tat com.example.E.e(E.java:50)
\t... 2 more
"""
    assert fingerprint(variant) == fingerprint(BASE)


def test_explicit_tail_equals_collapsed_tail():
    variant = """com.example.TopException: boom
    at com.example.A.run(A.java:10)
    at com.example.B.go(B.java:20)
    Suppressed: com.example.SupOne: s1
        at com.example.C.work(C.java:30)
    Suppressed: com.example.SupTwo: s2
        at com.example.D.deep(D.java:40)
Caused by: com.example.RootCause: why
    at com.example.E.e(E.java:50)
    at com.example.A.run(A.java:10)
    at com.example.B.go(B.java:20)
"""
    assert fingerprint(variant) == fingerprint(BASE)


def test_mixed_indent_units():
    variant = BASE.replace("\t", "    ")
    assert fingerprint(variant) == fingerprint(BASE)
    mixed = """com.example.TopException: boom
    \tat com.example.A.run(A.java:10)
\t    at com.example.B.go(B.java:20)
\tSuppressed: com.example.SupOne: s1
\t    \tat com.example.C.work(C.java:30)
Caused by: com.example.RootCause: why
\tat com.example.E.e(E.java:50)
\t... 1 more
"""
    # Different structure (only one suppressed, shorter tail) but parses.
    assert isinstance(fingerprint(mixed), str)


def test_wrapper_layer_change_splits():
    variant = BASE.replace(
        "Caused by: com.example.RootCause: why",
        "Caused by: com.example.Middle: m\n\tat com.example.M.m(M.java:1)"
        "\n\tat com.example.M.n(M.java:2)"
        "\nCaused by: com.example.RootCause: why",
    )
    assert fingerprint(variant) != fingerprint(BASE)


def test_frame_change_splits():
    variant = BASE.replace("at com.example.B.go(B.java:20)",
                           "at com.example.B.go2(B.java:20)")
    assert fingerprint(variant) != fingerprint(BASE)
    # Case sensitivity of class and method names.
    variant = BASE.replace("at com.example.B.go(B.java:20)",
                           "at com.example.B.Go(B.java:20)")
    assert fingerprint(variant) != fingerprint(BASE)


def test_duplicate_suppressed_count_matters():
    one = """com.example.Top: t
\tat com.example.A.run(A.java:1)
\tSuppressed: com.example.S: s
\t\tat com.example.B.go(B.java:2)
"""
    two = """com.example.Top: t
\tat com.example.A.run(A.java:1)
\tSuppressed: com.example.S: s
\t\tat com.example.B.go(B.java:2)
\tSuppressed: com.example.S: s
\t\tat com.example.B.go(B.java:2)
"""
    assert fingerprint(one) != fingerprint(two)
    # Duplicates commute: swapping identical blocks changes nothing.
    assert fingerprint(two) == fingerprint(two)


def test_frame_repetition_matters():
    variant = BASE.replace(
        "\tat com.example.B.go(B.java:20)",
        "\tat com.example.B.go(B.java:20)\n\tat com.example.B.go(B.java:20)",
    )
    assert fingerprint(variant) != fingerprint(BASE)


def test_nested_suppressed_cause_not_confused_with_outer():
    text = """com.example.A: a
\tat com.example.F.f1(F.java:1)
\tSuppressed: com.example.B: b
\t\tat com.example.F.f2(F.java:2)
\tCaused by: com.example.C: c
\t\tat com.example.F.f3(F.java:3)
Caused by: com.example.D: d
\tat com.example.F.f4(F.java:4)
"""
    interner = FrameInterner()
    root = parse_report(text, interner)
    assert root.class_name == "com.example.A"
    assert root.cause.class_name == "com.example.D"
    suppressed = root.suppressed[0]
    assert suppressed.class_name == "com.example.B"
    assert suppressed.cause.class_name == "com.example.C"
    assert root.cause.cause is None


def test_consecutive_collapse_chains():
    text = """com.example.A: a
\tat com.example.F.f1(F.java:1)
\tat com.example.F.f2(F.java:2)
Caused by: com.example.B: b
\tat com.example.F.f3(F.java:3)
\t... 2 more
Caused by: com.example.C: c
\tat com.example.F.f4(F.java:4)
\t... 3 more
"""
    explicit = """com.example.A: a
\tat com.example.F.f1(F.java:1)
\tat com.example.F.f2(F.java:2)
Caused by: com.example.B: b
\tat com.example.F.f3(F.java:3)
\tat com.example.F.f1(F.java:1)
\tat com.example.F.f2(F.java:2)
Caused by: com.example.C: c
\tat com.example.F.f4(F.java:4)
\tat com.example.F.f3(F.java:3)
\tat com.example.F.f1(F.java:1)
\tat com.example.F.f2(F.java:2)
"""
    assert fingerprint(text) == fingerprint(explicit)


def test_same_message_does_not_merge():
    first = """com.example.Top: same message
\tat com.example.A.run(A.java:1)
"""
    second = """com.example.Top: same message
\tat com.example.B.run(B.java:1)
"""
    assert fingerprint(first) != fingerprint(second)


def test_deep_cause_chain_no_recursion_error():
    depth = 5000
    parts = ["com.example.E0: x", "\tat com.example.F.f(F.java:1)"]
    for i in range(1, depth):
        parts.append(f"Caused by: com.example.E{i}: x")
        parts.append("\tat com.example.F.f(F.java:1)")
    text = "\n".join(parts) + "\n"
    assert isinstance(fingerprint(text), str)
    assert group_reports([text, text]) == [[0, 1]]
