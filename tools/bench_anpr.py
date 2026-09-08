"""Regression check for the ANPR cascade against captured grid frames.

Snapshot filenames are cam<NN>_<PLATE>_<ts>.jpg, where <PLATE> is what the
pipeline read at capture time. So this measures reproducibility, NOT accuracy:
the labels came from this same cascade, not from a human. It catches
regressions and gives a per-frame timing figure. Real accuracy needs hand
labelled plates.

Usage:
    python tools/bench_anpr.py <snapshot_dir> [--limit 25]
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

NAMED = re.compile(r"^cam\d+_([A-Z0-9]+)_\d+\.jpg$", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot_dir", type=Path)
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    import cv2  # noqa: E402
    from app.anpr.pipeline import read_plates  # noqa: E402

    files, seen = [], set()
    for f in sorted(args.snapshot_dir.glob("*.jpg")):
        m = NAMED.match(f.name)
        if not m:
            continue
        plate = m.group(1).upper()
        if plate in seen:          # one frame per plate, so a common vehicle
            continue               # doesn't dominate the sample
        seen.add(plate)
        files.append((f, plate))
        if len(files) >= args.limit:
            break

    if not files:
        sys.exit(f"no labelled snapshots in {args.snapshot_dir}")

    exact = partial = miss = 0
    times = []
    print(f"{'expected':<14} {'read':<14} {'conf':>5} {'s':>6}  result")
    for f, expected in files:
        frame = cv2.imread(str(f))
        if frame is None:
            print(f"{expected:<14} {'UNREADABLE':<14}")
            miss += 1
            continue

        t0 = time.perf_counter()
        try:
            reads = read_plates(frame)
        except Exception as e:
            print(f"{expected:<14} {'ERROR':<14} {'':>5} {'':>6}  {e}")
            miss += 1
            continue
        dt = time.perf_counter() - t0
        times.append(dt)

        best = max(((r.plate, r.confidence) for r in reads if r.plate),
                   key=lambda p: p[1], default=("", 0.0))
        read, conf = best

        if read == expected:
            exact += 1
            verdict = "exact"
        elif read and (read in expected or expected in read):
            partial += 1
            verdict = "partial"
        else:
            miss += 1
            verdict = "miss"
        print(f"{expected:<14} {read or '-':<14} {conf:>5.2f} {dt:>6.2f}  {verdict}")

    n = len(files)
    avg = sum(times) / len(times) if times else 0
    print(f"\n{n} frames | exact {exact} ({100*exact/n:.0f}%) | "
          f"partial {partial} | miss {miss} | avg {avg:.2f}s/frame")


if __name__ == "__main__":
    main()
