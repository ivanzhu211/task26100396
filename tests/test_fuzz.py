"""Randomized fuzz: library fingerprint == brute-force expansion reference."""

from __future__ import annotations

import random

from crashgroup import fingerprint_report, group_reports
from crashgroup.parser import ExceptionNode, parse_report
from tests.test_correctness import canonical

FRAME_POOL = [f"com.p.C{i}.m{j}" for i in range(6) for j in range(4)]
CLASS_POOL = [f"com.e.E{i}" for i in range(6)]


def build_tree(rng: random.Random, depth: int) -> ExceptionNode:
    node = ExceptionNode(class_name=rng.choice(CLASS_POOL))
    node.frames = [rng.choice(FRAME_POOL) for _ in range(rng.randint(0, 5))]
    if depth > 0:
        if rng.random() < 0.6:
            node.cause = build_tree(rng, depth - 1)
            node.cause.parent = node
        for _ in range(rng.randint(0, 2)):
            if rng.random() < 0.7:
                child = build_tree(rng, depth - 1)
                child.parent = node
                node.suppressed.append(child)
    return node


def full_frames(node: ExceptionNode, memo: dict[int, tuple]) -> tuple:
    key = id(node)
    if key not in memo:
        tail = ()
        if node.parent is not None and node.collapsed:
            tail = full_frames(node.parent, memo)[-node.collapsed:]
        memo[key] = tuple(node.frames) + tail
    return memo[key]


def assign_collapses(root: ExceptionNode, rng: random.Random) -> None:
    """Pick a valid random collapse count for every non-root node."""
    memo: dict[int, tuple] = {}
    stack = [root]
    root.collapsed = 0
    while stack:
        node = stack.pop()
        for child in ([node.cause] if node.cause else []) + node.suppressed:
            parent_len = len(full_frames(node, memo))
            child.collapsed = rng.randint(0, parent_len) if parent_len else 0
            if child.collapsed and rng.random() < 0.4:
                # materialize part of the tail explicitly, collapse the rest
                explicit = rng.randint(0, child.collapsed)
                tail = full_frames(node, memo)[-child.collapsed:]
                child.frames = child.frames + list(tail[:explicit])
                child.collapsed -= explicit
            stack.append(child)


def render(node: ExceptionNode, rng: random.Random, expand: bool,
           memo: dict[int, tuple], level: int = 0,
           caption: str = "") -> list[str]:
    indent_unit = rng.choice(["\t", "    "])
    indent = indent_unit * level
    msg = f": msg{rng.randint(0, 999)}" if rng.random() < 0.5 else ""
    lines = [f"{indent}{caption}{node.class_name}{msg}"]
    frames = list(node.frames)
    collapsed = node.collapsed
    if expand:
        frames = list(full_frames(node, memo))
        collapsed = 0
    for frame in frames:
        loc = rng.choice([f"X.java:{rng.randint(1, 999)}", "Native Method",
                          "Unknown Source"])
        lines.append(f"{indent}{rng.choice([chr(9), '    '])}at {frame}({loc})")
    if collapsed:
        lines.append(f"{indent}{indent_unit}... {collapsed} more")
    suppressed = list(node.suppressed)
    if expand:
        rng.shuffle(suppressed)
    for child in suppressed:
        lines += render(child, rng, expand, memo, level + 1, "Suppressed: ")
    if node.cause is not None:
        lines += render(node.cause, rng, expand, memo, level, "Caused by: ")
    return lines


def random_report(rng: random.Random) -> tuple[str, str]:
    root = build_tree(rng, depth=4)
    assign_collapses(root, rng)
    memo: dict[int, tuple] = {}
    original = "\n".join(render(root, rng, False, memo)) + "\n"
    normalized = "\n".join(render(root, rng, True, memo)) + "\n"
    return original, normalized


def test_collapsed_and_expanded_variants_match():
    rng = random.Random(20261003)
    for _ in range(300):
        original, normalized = random_report(rng)
        assert fingerprint_report(original) == fingerprint_report(normalized)


def test_library_grouping_matches_reference():
    rng = random.Random(7)
    reports = []
    for i in range(120):
        original, _ = random_report(rng)
        reports.append((i, original))
    lib_groups = {frozenset(g) for g in group_reports(reports)}
    ref_groups: dict[tuple, set] = {}
    for i, text in reports:
        key = canonical(parse_report(text), {})
        ref_groups.setdefault(key, set()).add(i)
    assert lib_groups == {frozenset(g) for g in ref_groups.values()}


def test_single_mutation_splits_group():
    rng = random.Random(99)
    checked = 0
    for _ in range(200):
        original, _ = random_report(rng)
        root = parse_report(original)
        nodes: list[ExceptionNode] = []
        stack = [root]
        while stack:
            cur = stack.pop()
            nodes.append(cur)
            if cur.cause:
                stack.append(cur.cause)
            stack.extend(cur.suppressed)
        target = rng.choice(nodes)
        if not target.frames:
            continue
        memo: dict[int, tuple] = {}
        before = canonical(root, memo)
        saved = target.frames[0]
        target.frames[0] = saved + "X"
        after = canonical(root, {})
        target.frames[0] = saved
        if before == after:
            continue  # mutation collided with an identical frame name
        mutated = original.replace(f"at {saved}(", f"at {saved}X(", 1)
        assert fingerprint_report(original) != fingerprint_report(mutated)
        checked += 1
    assert checked > 50
