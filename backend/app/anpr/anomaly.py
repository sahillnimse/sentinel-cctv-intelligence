"""Per-camera anomaly detection over the person channel.

Two detectors, both deliberately relative to the camera's own history rather
than to one statewide threshold. A bus terminal at forty people is ordinary and
a rural junction at fifteen is not, so a fixed number would either drown the
operator in false alerts at the terminal or say nothing at the junction.

  crowd_surge  the count clears a floor AND a multiple of this camera's own
               rolling median. The floor exists because a lane going from one
               person to three is a 3x jump and not a crowd.

  loitering    a person track stays inside a small radius for longer than the
               dwell threshold. Anchored rather than averaged: someone who
               walks away resets their own anchor instead of slowly dragging a
               mean along behind them.

State is per camera and owned by that camera's worker thread, so nothing here
needs locking. Nothing here touches the database; the worker persists what it
is handed.
"""

from __future__ import annotations

import statistics
from collections import deque

from ..config import settings

# Samples needed before a baseline means anything. Without this the first busy
# frame after startup fires against a median of zero.
MIN_BASELINE_SAMPLES = 10
BASELINE_WINDOW = 240        # samples kept per camera (~20 min at 5 s)
TRACK_TTL_SECONDS = 12.0     # a track not seen for this long is gone


class CameraState:
    """Rolling crowd baseline and person tracks for one camera."""

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self._counts: deque[int] = deque(maxlen=BASELINE_WINDOW)
        self._tracks: list[dict] = []
        self._last_fired: dict[str, float] = {}

    # --- baseline ---------------------------------------------------------

    @property
    def baseline(self) -> float:
        """Median person count for this camera, or 0 while still learning."""
        if len(self._counts) < MIN_BASELINE_SAMPLES:
            return 0.0
        return float(statistics.median(self._counts))

    @property
    def samples(self) -> int:
        return len(self._counts)

    # --- main entry point -------------------------------------------------

    def observe(self, person_boxes, frame_shape, mono_now: float) -> list[dict]:
        """Record one frame's people; return any anomalies it triggered."""
        count = len(person_boxes)
        events: list[dict] = []

        if settings.anomaly_enabled:
            surge = self._check_surge(count, mono_now)
            if surge:
                events.append(surge)
            events.extend(self._check_loitering(person_boxes, frame_shape, mono_now))

        # Recorded after the surge check so a camera cannot normalise away the
        # very spike being tested.
        self._counts.append(count)
        return events

    # --- detectors --------------------------------------------------------

    def _check_surge(self, count: int, mono_now: float) -> dict | None:
        baseline = self.baseline
        if baseline <= 0:
            return None
        if count < settings.crowd_surge_min_people:
            return None
        if count < baseline * settings.crowd_surge_ratio:
            return None
        if not self._fire_ok("crowd_surge", mono_now):
            return None
        ratio = count / baseline
        severity = "critical" if ratio >= settings.crowd_surge_ratio * 2 else "warning"
        return {
            "kind": "crowd_surge",
            "severity": severity,
            "value": float(count),
            "baseline": round(baseline, 2),
            "detail": (f"{count} people in frame against a rolling median of "
                       f"{baseline:g} for this camera ({ratio:.1f}x)"),
        }

    def _check_loitering(self, person_boxes, frame_shape, mono_now: float) -> list[dict]:
        width = max(frame_shape[1], 1) if len(frame_shape) > 1 else 1
        radius = max(width * settings.loiter_radius_frac, 8.0)

        self._tracks = [t for t in self._tracks
                        if mono_now - t["last"] < TRACK_TTL_SECONDS]

        for box in person_boxes:
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            track = self._nearest(cx, cy, radius * 2.0)
            if track is None:
                self._tracks.append({
                    "cx": cx, "cy": cy, "ax": cx, "ay": cy,
                    "first": mono_now, "last": mono_now, "fired": False,
                })
                continue
            track["cx"], track["cy"], track["last"] = cx, cy, mono_now
            drift = ((cx - track["ax"]) ** 2 + (cy - track["ay"]) ** 2) ** 0.5
            if drift > radius:
                # They moved on. Re-anchor and restart the clock rather than
                # letting a slow walk across the scene accumulate dwell time.
                track.update(ax=cx, ay=cy, first=mono_now, fired=False)

        events = []
        for track in self._tracks:
            if track["fired"]:
                continue
            dwell = track["last"] - track["first"]
            if dwell < settings.loiter_seconds:
                continue
            if not self._fire_ok("loitering", mono_now):
                break
            track["fired"] = True
            events.append({
                "kind": "loitering",
                "severity": "warning",
                "value": round(dwell, 1),
                "baseline": float(settings.loiter_seconds),
                "detail": (f"a person stayed within {int(radius)} px for "
                           f"{int(dwell)}s, past the {int(settings.loiter_seconds)}s "
                           f"dwell threshold"),
            })
        return events

    # --- helpers ----------------------------------------------------------

    def _nearest(self, cx: float, cy: float, radius: float) -> dict | None:
        best, best_d = None, radius
        for t in self._tracks:
            d = ((t["cx"] - cx) ** 2 + (t["cy"] - cy) ** 2) ** 0.5
            if d < best_d:
                best, best_d = t, d
        return best

    def _fire_ok(self, kind: str, mono_now: float) -> bool:
        """One anomaly of a kind per camera per dedup window."""
        last = self._last_fired.get(kind)
        if last is not None and mono_now - last < settings.anomaly_dedup_seconds:
            return False
        self._last_fired[kind] = mono_now
        return True
