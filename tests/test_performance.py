"""Reproducible performance tests at the required scale.

Run with ``pytest -s tests/test_performance.py`` to see timing/memory.
Limits from the spec: < 10 s per report, < 256 MiB peak memory.
"""

from __future__ import annotations

import time
import tracemalloc

from crashgroup import fingerprint_report

TIME_LIMIT_S = 10.0
MEM_LIMIT_BYTES = 256 * 1024 * 1024

DEPTH = 20_000          # cause-chain depth / suppressed count
ROOT_FRAMES = 50_000    # explicit frames on the shared root


def build_deep_chain_report(depth: int = DEPTH) -> str:
    """20k-level cause chain; every level collapses 1 frame from its outer.

    Each tail query must walk the whole ancestor chain (binary lifting
    stress). Total logical frames = depth*(depth+1)/2 ~ 2e8.
    """
    parts = ["com.e.E0"]
    for i in range(1, depth + 1):
        parts.append(f"\tat com.f.F{i}.m(F{i}.java:1)")
        parts.append(f"Caused by: com.e.E{i}")
    parts.append(f"\tat com.f.F{depth}.m(F{depth}.java:1)")
    # add a "... 1 more" collapse line to every non-top exception
    lines = []
    cause_seen = 0
    for line in parts:
        lines.append(line)
        if line.startswith("Caused by:"):
            cause_seen += 1
            lines.append(f"\tat com.f.G{cause_seen}.m(G{cause_seen}.java:1)")
            lines.append("\t... 1 more")
    return "\n".join(lines) + "\n"


def build_shared_tail_report(root_frames: int = ROOT_FRAMES,
                             suppressed: int = DEPTH) -> str:
    """Shallow report: huge root frame list shared by 20k suppressed
    exceptions via collapse lines of 1000 distinct lengths (~1e9 logical
    frames in total)."""
    parts = ["com.e.Root"]
    for i in range(root_frames):
        parts.append(f"\tat com.r.R{i % 500}.m{i % 97}(R.java:{i % 1000})")
    for i in range(suppressed):
        n = root_frames - (i % 1000)
        parts.append(f"\tSuppressed: com.e.S{i % 100}")
        parts.append(f"\t\tat com.s.T{i % 300}.u(T.java:1)")
        parts.append(f"\t\t... {n} more")
    return "\n".join(parts) + "\n"


def measure(text: str) -> tuple[str, float, int]:
    tracemalloc.start()
    start = time.perf_counter()
    fp = fingerprint_report(text)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return fp, elapsed, peak


def check(label: str, text: str) -> None:
    fp, elapsed, peak = measure(text)
    print(f"\n[{label}] size={len(text)/2**20:.2f} MiB "
          f"time={elapsed:.2f}s peak={peak/2**20:.1f} MiB fp={fp[:16]}...")
    assert elapsed < TIME_LIMIT_S, f"{label}: {elapsed:.2f}s >= {TIME_LIMIT_S}s"
    assert peak < MEM_LIMIT_BYTES, f"{label}: peak {peak/2**20:.1f} MiB"


def test_deep_cause_chain():
    check("deep-cause-chain-20k", build_deep_chain_report())


def test_many_suppressed_shared_tails():
    check("shared-tails-1e9-frames", build_shared_tail_report())


def test_deterministic_across_runs():
    text = build_shared_tail_report(root_frames=2000, suppressed=500)
    assert fingerprint_report(text) == fingerprint_report(text)
