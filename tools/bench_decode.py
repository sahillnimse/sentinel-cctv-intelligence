"""Measure how many camera streams this box can actually decode.

Runs N ffmpeg processes against the same file and reports aggregate decoded
fps. The point is to find the ceiling per decode backend so the scheduler in
config/system.yaml gets real numbers instead of guesses.

Stdlib only, so it runs before any venv exists.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKENDS = {
    "cuda": ["-hwaccel", "cuda", "-c:v", "h264_cuvid"],
    "amf": ["-c:v", "h264_amf"],
    "qsv": ["-hwaccel", "qsv", "-c:v", "h264_qsv"],
    "d3d11va": ["-hwaccel", "d3d11va"],
    "cpu": [],
}


def build_cmd(video, backend, duration):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats"]
    cmd += BACKENDS[backend]
    cmd += ["-i", str(video)]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-f", "null", "-", "-progress", "pipe:1"]
    return cmd


def parse_progress(text):
    """Pull the last frame= and speed= out of ffmpeg's -progress output."""
    frames, speed = 0, None
    for line in text.splitlines():
        if line.startswith("frame="):
            try:
                frames = int(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("speed="):
            speed = line.split("=", 1)[1].strip()
    return frames, speed


def run(video, backend, streams, duration):
    procs = []
    start = time.perf_counter()
    for _ in range(streams):
        procs.append(subprocess.Popen(
            build_cmd(video, backend, duration),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ))

    total_frames = 0
    failures = 0
    speeds = []
    for p in procs:
        out, err = p.communicate()
        if p.returncode != 0:
            failures += 1
            if failures == 1:
                print(f"  first failure: {err.strip().splitlines()[-1] if err.strip() else 'no stderr'}",
                      file=sys.stderr)
            continue
        f, s = parse_progress(out)
        total_frames += f
        if s:
            speeds.append(s)

    wall = time.perf_counter() - start
    return {
        "backend": backend,
        "streams": streams,
        "ok": streams - failures,
        "failed": failures,
        "wall_s": round(wall, 2),
        "total_frames": total_frames,
        "aggregate_fps": round(total_frames / wall, 1) if wall else 0,
        "per_stream_fps": round(total_frames / wall / max(streams - failures, 1), 1) if wall else 0,
        "speeds": speeds[:3],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--backend", default="cuda", choices=list(BACKENDS))
    ap.add_argument("--streams", default="1,2,4,8,12,16",
                    help="comma separated stream counts to sweep")
    ap.add_argument("--duration", type=int, default=20, help="seconds of video per run")
    ap.add_argument("--out", type=Path, help="write results as json")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not on PATH")
    if not args.video.exists():
        sys.exit(f"no such file: {args.video}")

    counts = [int(x) for x in args.streams.split(",")]
    results = []
    print(f"{args.backend} decode, {args.duration}s per run, {args.video.name}\n")
    print(f"{'streams':>8} {'ok':>4} {'agg fps':>9} {'per-stream':>11} {'wall':>7}")
    for n in counts:
        r = run(args.video, args.backend, n, args.duration)
        results.append(r)
        print(f"{r['streams']:>8} {r['ok']:>4} {r['aggregate_fps']:>9} "
              f"{r['per_stream_fps']:>11} {r['wall_s']:>7}")
        if r["failed"]:
            print(f"         {r['failed']} stream(s) failed, backend limit probably hit")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
