"""Correctness tests: library vs brute-force full-expansion reference."""

from __future__ import annotations

import random

from crashgroup import fingerprint_report, group_reports
from crashgroup.parser import ExceptionNode, parse_report


# --- brute-force reference: expand everything, compare by business rules ---

def expand_frames(node: ExceptionNode, memo: dict[int, tuple]) -> tuple:
    key = id(node)
    if key not in memo:
        parent_tail = ()
        if node.collapsed:
            parent_tail = expand_frames(node.parent, memo)[-node.collapsed:]
        memo[key] = tuple(node.frames) + parent_tail
    return memo[key]


def canonical(node: ExceptionNode, memo: dict[int, tuple]):
    frames = expand_frames(node, memo)
    cause = canonical(node.cause, memo) if node.cause else None
    sup = sorted(canonical(ch, memo) for ch in node.suppressed)
    return (node.class_name, frames, cause, tuple(sup))


def reference_key(text: str):
    return canonical(parse_report(text), {})


def assert_same_group(a: str, b: str) -> None:
    assert reference_key(a) == reference_key(b), "reference says different"
    assert fingerprint_report(a) == fingerprint_report(b)


def assert_different_group(a: str, b: str) -> None:
    assert reference_key(a) != reference_key(b), "reference says same"
    assert fingerprint_report(a) != fingerprint_report(b)


# --- targeted scenarios ---

def test_interleaved_cause_and_suppressed_nesting():
    text = """java.lang.Top: t
\tat a.F1(A.java:1)
\tSuppressed: java.lang.S1
\t\tat a.F2(A.java:2)
\tCaused by: java.lang.CauseOfS1
\t\tat a.F3(A.java:3)
\t\t... 1 more
\tSuppressed: java.lang.S2
\t\tat a.F4(A.java:4)
Caused by: java.lang.CauseOfTop
\tat a.F5(A.java:5)
\t... 2 more
"""
    # inner "Caused by" belongs to S1, not to Top
    root = parse_report(text)
    assert root.cause.class_name == "java.lang.CauseOfTop"
    assert root.suppressed[0].cause.class_name == "java.lang.CauseOfS1"
    assert root.suppressed[1].cause is None


def test_chained_collapse_matches_manual_expansion():
    collapsed = """java.lang.A
\tat x.F1(X.java:1)
\tat x.F2(X.java:2)
\tat x.F3(X.java:3)
Caused by: java.lang.B
\tat x.G1(X.java:4)
\t... 3 more
Caused by: java.lang.C
\tat x.H1(X.java:5)
\t... 4 more
"""
    expanded = """java.lang.A
\tat x.F1(X.java:1)
\tat x.F2(X.java:2)
\tat x.F3(X.java:3)
Caused by: java.lang.B
\tat x.G1(X.java:4)
\tat x.F1(X.java:1)
\tat x.F2(X.java:2)
\tat x.F3(X.java:3)
Caused by: java.lang.C
\tat x.H1(X.java:5)
\tat x.G1(X.java:4)
\tat x.F1(X.java:1)
\tat x.F2(X.java:2)
\tat x.F3(X.java:3)
"""
    assert_same_group(collapsed, expanded)


def test_suppressed_collapse_references_owner_not_nearest_text():
    # S1's cause appears textually between owner and S2; S2's collapse
    # must still resolve against its owner (Top), not CauseOfS1.
    text = """java.lang.Top
\tat a.F1(A.java:1)
\tat a.F2(A.java:2)
\tSuppressed: java.lang.S1
\t\tat a.G1(A.java:3)
\tCaused by: java.lang.CauseOfS1
\t\tat a.H1(A.java:4)
\tSuppressed: java.lang.S2
\t\tat a.G2(A.java:5)
\t\t... 2 more
"""
    expanded = """java.lang.Top
\tat a.F1(A.java:1)
\tat a.F2(A.java:2)
\tSuppressed: java.lang.S1
\t\tat a.G1(A.java:3)
\tCaused by: java.lang.CauseOfS1
\t\tat a.H1(A.java:4)
\tSuppressed: java.lang.S2
\t\tat a.G2(A.java:5)
\t\tat a.F1(A.java:1)
\t\tat a.F2(A.java:2)
"""
    assert_same_group(text, expanded)


def test_ignored_fields_do_not_change_fingerprint():
    base = """java.lang.A: message one
\tat a.M(A.java:1)
\tat b.N(Native Method)
Caused by: java.lang.B: cause msg
\tat c.O(Unknown Source)
\t... 2 more
"""
    variant = """java.lang.A: completely different message
    at a.M(A.java:777)
    at b.N(B.java:42)
Caused by: java.lang.B
    at c.O(C.java:13)
    at a.M(A.java:1)
    at b.N(B.java:2)
"""
    assert_same_group(base, variant)


def test_suppressed_order_swap_keeps_group():
    a = """java.lang.T
\tat a.F(A.java:1)
\tSuppressed: java.lang.S1
\t\tat a.G(A.java:2)
\tSuppressed: java.lang.S2
\t\tat a.H(A.java:3)
"""
    b = """java.lang.T
\tat a.F(A.java:1)
\tSuppressed: java.lang.S2
\t\tat a.H(A.java:3)
\tSuppressed: java.lang.S1
\t\tat a.G(A.java:2)
"""
    assert_same_group(a, b)


def test_duplicate_suppressed_count_splits():
    a = """java.lang.T
\tat a.F(A.java:1)
\tSuppressed: java.lang.S1
\t\tat a.G(A.java:2)
"""
    b = """java.lang.T
\tat a.F(A.java:1)
\tSuppressed: java.lang.S1
\t\tat a.G(A.java:2)
\tSuppressed: java.lang.S1
\t\tat a.G(A.java:2)
"""
    assert_different_group(a, b)


def test_wrapper_layer_splits():
    inner = """java.lang.A
\tat a.M(A.java:1)
"""
    wrapped = """java.lang.Wrapper
\tat w.M(W.java:1)
Caused by: java.lang.A
\tat a.M(A.java:1)
"""
    assert_different_group(inner, wrapped)


def test_frame_change_and_frame_order_split():
    a = "java.lang.A\n\tat a.M(A.java:1)\n\tat a.N(A.java:2)\n"
    b = "java.lang.A\n\tat a.M(A.java:1)\n\tat a.N2(A.java:2)\n"
    c = "java.lang.A\n\tat a.N(A.java:2)\n\tat a.M(A.java:1)\n"
    assert_different_group(a, b)
    assert_different_group(a, c)


def test_case_sensitive_and_lambda_names_preserved():
    a = "java.lang.A\n\tat a.M(A.java:1)\n"
    b = "java.lang.A\n\tat a.m(A.java:1)\n"
    c = "java.lang.A\n\tat a.M$1(A.java:1)\n"
    d = "java.lang.A\n\tat a.M(A.java:1)\n"
    e = "java.lang.A\n\tat a.M(A.java:1)\n\tat a.lambda$run$0(A.java:2)\n"
    assert_different_group(a, b)
    assert_different_group(a, c)
    assert_same_group(a, d)
    assert_different_group(a, e)


def test_group_reports_returns_ids():
    r1 = "java.lang.A: x\n\tat a.M(A.java:1)\n"
    r2 = "java.lang.A: y\n\tat a.M(A.java:2)\n"
    r3 = "java.lang.B\n\tat a.M(A.java:1)\n"
    groups = group_reports([(1, r1), (2, r2), (3, r3), (4, r1)])
    assert groups == [[1, 2, 4], [3]]
