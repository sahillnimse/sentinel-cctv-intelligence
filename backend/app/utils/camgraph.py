"""
camgraph.py — Spatio-temporal route validation for cross-camera vehicle tracking.

Given a chronological set of camera sightings of one vehicle (each carrying a
camera location and timestamp), this module checks whether the movement between
consecutive cameras is *physically plausible*. If the vehicle would have had to
travel faster than a configurable ceiling (default 150 km/h) to get from one
camera to the next in the observed time, the later sighting is flagged as an
"impossible hop" — a strong signal of a mis-read plate, a cloned plate, or two
different vehicles being conflated.

Pure Python: standard library only (math + datetime). No heavy dependencies,
import-safe under any environment.

Public API:
    haversine(lat1, lon1, lat2, lon2) -> metres
    validate_route(points, max_speed_kmph=150.0) -> annotated list (same list)
    route_summary(points) -> dict
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

__all__ = ["haversine", "validate_route", "route_summary"]

# Mean Earth radius in metres (WGS-84 mean).
_EARTH_RADIUS_M = 6_371_000.0

# Small epsilon (seconds) used when two sightings share an identical timestamp,
# to avoid division-by-zero while keeping implied speed finite-but-large.
_TIME_EPSILON_S = 0.001


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in **metres**.

    Uses the haversine formula. Inputs are decimal degrees. Returns 0.0 if the
    two points are identical.
    """
    lat1 = float(lat1)
    lon1 = float(lon1)
    lat2 = float(lat2)
    lon2 = float(lon2)

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return _EARTH_RADIUS_M * c


def _has_coords(point: Dict[str, Any]) -> bool:
    """True if the point carries usable numeric latitude and longitude."""
    lat = point.get("latitude")
    lon = point.get("longitude")
    if lat is None or lon is None:
        return False
    try:
        float(lat)
        float(lon)
    except (TypeError, ValueError):
        return False
    return True


def _ts_key(point: Dict[str, Any]) -> float:
    """Sort key: POSIX seconds for the point's ts, or +inf if missing/bad.

    Points without a valid timestamp sort to the end so they never sit between
    two well-ordered sightings.
    """
    ts = point.get("ts")
    if isinstance(ts, datetime):
        try:
            return ts.timestamp()
        except (OverflowError, OSError, ValueError):
            return float("inf")
    return float("inf")


def validate_route(
    points: List[Dict[str, Any]],
    max_speed_kmph: float = 150.0,
) -> List[Dict[str, Any]]:
    """Validate a vehicle's cross-camera route in place.

    Args:
        points: list of dicts, each ideally with keys ``camera_id``,
            ``latitude``, ``longitude`` and ``ts`` (a ``datetime``). Extra keys
            are preserved untouched.
        max_speed_kmph: implied-speed ceiling above which a hop is flagged.

    Behaviour:
        * The list is sorted ascending by ``ts``.
        * For each consecutive pair the great-circle distance and elapsed time
          are computed; the implied speed = distance / time.
        * If the implied speed exceeds ``max_speed_kmph`` the **later** point is
          flagged with reason ``"impossible hop"``.
        * Consecutive sightings from the same camera are always fine (the vehicle
          may simply be dwelling); such hops get speed 0.
        * Identical timestamps get a tiny epsilon added to the elapsed time to
          avoid division by zero.
        * Points missing coordinates or timestamps cannot be checked and are
          left unflagged (with a descriptive reason where relevant).

    Returns:
        The same list object, with each point annotated with the float/bool
        keys ``gap_km``, ``gap_s``, ``speed_kmph``, ``flagged`` and the string
        key ``reason`` ('' when ok).
    """
    if not points:
        return points

    points.sort(key=_ts_key)

    # Initialise annotations on every point (the first point has no predecessor).
    for p in points:
        p["gap_km"] = 0.0
        p["gap_s"] = 0.0
        p["speed_kmph"] = 0.0
        p["flagged"] = False
        p["reason"] = ""

    for i in range(1, len(points)):
        prev = points[i - 1]
        cur = points[i]

        # Need valid timestamps on both ends to compute an elapsed time.
        prev_ts = prev.get("ts")
        cur_ts = cur.get("ts")
        if not isinstance(prev_ts, datetime) or not isinstance(cur_ts, datetime):
            cur["reason"] = "missing timestamp"
            continue

        gap_s = (cur_ts - prev_ts).total_seconds()
        # Guard against out-of-order / identical timestamps.
        if gap_s <= 0.0:
            gap_s = _TIME_EPSILON_S
        cur["gap_s"] = gap_s

        # Same camera -> the vehicle hasn't moved; distance/speed are zero.
        same_camera = (
            prev.get("camera_id") is not None
            and prev.get("camera_id") == cur.get("camera_id")
        )
        if same_camera:
            cur["gap_km"] = 0.0
            cur["speed_kmph"] = 0.0
            continue

        # Need coordinates on both ends to compute a distance.
        if not _has_coords(prev) or not _has_coords(cur):
            cur["reason"] = "missing coordinates"
            continue

        dist_m = haversine(
            float(prev["latitude"]),
            float(prev["longitude"]),
            float(cur["latitude"]),
            float(cur["longitude"]),
        )
        gap_km = dist_m / 1000.0
        speed_kmph = gap_km / (gap_s / 3600.0)

        cur["gap_km"] = gap_km
        cur["speed_kmph"] = speed_kmph

        if speed_kmph > max_speed_kmph:
            cur["flagged"] = True
            cur["reason"] = "impossible hop"

    return points


def route_summary(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarise a (validated or raw) route.

    Returns a dict with:
        total_distance_km (float): sum of per-hop gap_km (computed from coords
            if not already annotated).
        total_duration_s (float): seconds between first and last valid ts.
        cameras_touched (int): count of distinct camera_id values.
        first_seen (datetime | None): earliest valid timestamp.
        last_seen (datetime | None): latest valid timestamp.
        flagged_count (int): number of points flagged as impossible hops.

    Robust to empty lists and points missing coordinates or timestamps.
    """
    summary: Dict[str, Any] = {
        "total_distance_km": 0.0,
        "total_duration_s": 0.0,
        "cameras_touched": 0,
        "first_seen": None,
        "last_seen": None,
        "flagged_count": 0,
    }
    if not points:
        return summary

    ordered = sorted(points, key=_ts_key)

    cameras = {
        p.get("camera_id") for p in ordered if p.get("camera_id") is not None
    }
    summary["cameras_touched"] = len(cameras)

    summary["flagged_count"] = sum(1 for p in ordered if p.get("flagged"))

    timestamps = [p.get("ts") for p in ordered if isinstance(p.get("ts"), datetime)]
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    if timestamps:
        first_seen = min(timestamps)
        last_seen = max(timestamps)
        summary["first_seen"] = first_seen
        summary["last_seen"] = last_seen
        summary["total_duration_s"] = (last_seen - first_seen).total_seconds()

    # Total distance: prefer existing gap_km annotations; otherwise derive from
    # consecutive coordinates.
    total_km = 0.0
    has_annotations = any("gap_km" in p for p in ordered)
    if has_annotations:
        total_km = sum(float(p.get("gap_km", 0.0) or 0.0) for p in ordered)
    else:
        for i in range(1, len(ordered)):
            prev, cur = ordered[i - 1], ordered[i]
            if _has_coords(prev) and _has_coords(cur):
                total_km += haversine(
                    float(prev["latitude"]),
                    float(prev["longitude"]),
                    float(cur["latitude"]),
                    float(cur["longitude"]),
                ) / 1000.0
    summary["total_distance_km"] = total_km

    return summary


if __name__ == "__main__":
    from datetime import timedelta, timezone

    now = datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc)

    # Ahmedabad -> Gandhinagar (~25 km) in 30 min = ~50 km/h (plausible),
    # then Gandhinagar -> Surat (~230 km) in 2 min (impossible).
    demo = [
        {
            "camera_id": 1,
            "latitude": 23.0225,
            "longitude": 72.5714,  # Ahmedabad
            "ts": now,
        },
        {
            "camera_id": 2,
            "latitude": 23.2156,
            "longitude": 72.6369,  # Gandhinagar
            "ts": now + timedelta(minutes=30),
        },
        {
            "camera_id": 3,
            "latitude": 21.1702,
            "longitude": 72.8311,  # Surat
            "ts": now + timedelta(minutes=32),
        },
    ]

    validated = validate_route(demo, max_speed_kmph=150.0)
    print("=== validate_route ===")
    for p in validated:
        print(
            f"cam {p['camera_id']}: "
            f"gap_km={p['gap_km']:.2f} "
            f"gap_s={p['gap_s']:.1f} "
            f"speed_kmph={p['speed_kmph']:.1f} "
            f"flagged={p['flagged']} "
            f"reason={p['reason']!r}"
        )

    print("\n=== route_summary ===")
    for k, v in route_summary(validated).items():
        print(f"{k}: {v}")

    # Sanity assertions for the smoke test.
    assert validated[0]["flagged"] is False, "first point should never flag"
    assert validated[1]["flagged"] is False, "plausible hop should not flag"
    assert validated[2]["flagged"] is True, "impossible hop must be flagged"
    assert route_summary(validated)["flagged_count"] == 1
    assert route_summary([]) == {
        "total_distance_km": 0.0,
        "total_duration_s": 0.0,
        "cameras_touched": 0,
        "first_seen": None,
        "last_seen": None,
        "flagged_count": 0,
    }
    print("\nOK: smoke test passed.")
