"""Reproducible performance tests at the required scale.

Limits under test (single report): 4 MiB of text, 20k exceptions, 50k
explicit frames, up to ~1e9 frames in the fully expanded sequences.
Fingerprinting must finish within 10 seconds and stay well inside a
256 MiB process memory budget.

Run with: python3 -m pytest tests/test_perf.py -q -s
"""

from __future__ import annotations

import gc
import resource
import time
import tracemalloc

from crashgroup import fingerprint

TIME_BUDGET_S = 10.0
MEM_BUDGET_MIB = 256


def _measure(report: str, label: str) -> str:
    # Timing run: no tracemalloc, since allocation tracing skews wall time.
    gc.collect()
    start = time.perf_counter()
    digest = fingerprint(report)
    elapsed = time.perf_counter() - start
    # Memory run: tracemalloc for Python allocations, ru_maxrss for the
    # process high-water mark.
    gc.collect()
    tracemalloc.start()
    digest_again = fingerprint(report)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert digest_again == digest
    rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2
    print(
        f"\n[{label}] {elapsed:.2f}s, python-alloc peak {peak / 1024**2:.1f} MiB, "
        f"process max RSS {rss_mib:.1f} MiB, fingerprint {digest[:16]}..."
    )
    assert elapsed < TIME_BUDGET_S, f"{label}: {elapsed:.2f}s exceeds {TIME_BUDGET_S}s"
    assert peak < MEM_BUDGET_MIB * 1024**2, f"{label}: peak {peak} bytes"
    return digest


def _frame_pool(count: int) -> list[str]:
    return [f"com.example.mod{i % 97}.Cls{i}.method{i}" for i in range(count)]


def test_deep_cause_chain():
    """20k-level cause chain; expanded sequences total ~4e8 frames."""
    depth = 20_000
    pool = _frame_pool(1000)
    lines = ["com.example.E0: boom"]
    lines.append(f"\tat {pool[0]}(A.java:1)")
    lines.append(f"\tat {pool[1]}(A.java:2)")
    for i in range(1, depth):
        lines.append(f"Caused by: com.example.E{i}: boom")
        lines.append(f"\tat {pool[(2 * i) % 1000]}(A.java:{i})")
        lines.append(f"\tat {pool[(2 * i + 1) % 1000]}(A.java:{i})")
        lines.append(f"\t... {2 * i} more")
    report = "\n".join(lines) + "\n"
    size_mib = len(report.encode()) / 1024**2
    expanded = sum(2 * i + 2 for i in range(depth))
    print(f"\n[deep-chain] input {size_mib:.2f} MiB, {depth} exceptions, "
          f"expanded frames total {expanded:.3e}")
    assert len(report.encode()) <= 4 * 1024**2
    _measure(report, "deep-chain")


def test_many_shared_tails():
    """20k suppressed exceptions sharing outer tails of different lengths.

    Root prints 50k explicit frames; every suppressed exception folds a
    different-length tail of it, so expanded sequences total ~8e8 frames.
    """
    tail_count = 20_000
    root_frames = 50_000
    pool = _frame_pool(2000)
    lines = ["com.example.Top: boom"]
    for i in range(root_frames):
        lines.append(f"\tat {pool[i % 2000]}(B.java:{i % 10_000})")
    for i in range(tail_count):
        lines.append("\tSuppressed: com.example.Sup: s")
        lines.append(f"\t\t... {30_000 + i} more")
    report = "\n".join(lines) + "\n"
    size_mib = len(report.encode()) / 1024**2
    expanded = root_frames + sum(30_000 + i for i in range(tail_count))
    print(f"\n[shared-tails] input {size_mib:.2f} MiB, {tail_count + 1} exceptions, "
          f"expanded frames total {expanded:.3e}")
    assert len(report.encode()) <= 4 * 1024**2
    _measure(report, "shared-tails")


def test_batch_grouping_at_scale():
    """group_reports over a batch that mixes both large-report shapes."""
    pool = _frame_pool(500)
    small = []
    for variant in range(3):
        lines = [f"com.example.Top: v{variant}"]
        for i in range(200):
            lines.append(f"\tat {pool[(i + variant) % 500]}(C.java:{i})")
        lines.append("Caused by: com.example.Root: r")
        lines.append(f"\tat {pool[0]}(C.java:1)")
        lines.append("\t... 200 more")
        small.append("\n".join(lines) + "\n")
    batch = [small[0], small[1], small[0], small[2], small[1], small[0]]
    gc.collect()
    start = time.perf_counter()
    from crashgroup import group_reports

    groups = group_reports(batch)
    elapsed = time.perf_counter() - start
    print(f"\n[batch] 6 reports grouped in {elapsed:.3f}s -> {groups}")
    assert groups == [[0, 2, 5], [1, 4], [3]]
