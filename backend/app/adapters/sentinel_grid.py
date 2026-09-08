"""Adapter for the Sentinel sandbox grid (MediaMTX gateway).

The catalogue at /api/ingest is the contract; the URL pattern is not. Camera
ids change between sessions, so we always read the catalogue when we can and
only fall back to the documented cam01..cam30 range when it is unreachable —
which it is without a portal session cookie.
"""

import json
import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ..config import settings
from .base import AdapterInfo, DiscoveredCamera

log = logging.getLogger("sentinel.adapters.grid")

FALLBACK_COUNT = 30


class SentinelGridAdapter:
    key = "sentinel-grid"
    label = "Sentinel sandbox grid"
    vendor = "Gujarat Police / MediaMTX"
    protocols = ["RTSP", "HLS", "WebRTC-WHEP"]

    def configured(self) -> bool:
        return bool(settings.grid_rtsp_base)

    def info(self) -> AdapterInfo:
        detail = ("catalogue reachable" if self._catalogue()
                  else "catalogue behind login, using documented id range")
        return AdapterInfo(self.key, self.label, self.vendor, self.protocols,
                           self.configured(), detail)

    def _catalogue(self) -> list[dict] | None:
        url = settings.grid_catalog_url
        if not url:
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "sentinel-platform/1.0"})
        if settings.grid_access_cookie:
            req.add_header("Cookie", settings.grid_access_cookie)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace")
            data = json.loads(body)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            log.info("grid catalogue unavailable (%s)", exc)
            return None

        # The catalogue has been seen as both a bare list and wrapped.
        if isinstance(data, dict):
            for k in ("cameras", "items", "data", "results"):
                if isinstance(data.get(k), list):
                    return data[k]
            return None
        return data if isinstance(data, list) else None

    def discover(self) -> list[DiscoveredCamera]:
        rows = self._catalogue()
        if rows:
            return [self._from_catalogue(r) for r in rows]
        log.info("falling back to cam01..cam%02d", FALLBACK_COUNT)
        return [self._fallback(i) for i in range(1, FALLBACK_COUNT + 1)]

    def _from_catalogue(self, row: dict) -> DiscoveredCamera:
        cid = str(row.get("id") or row.get("camera_id") or row.get("name") or "").strip()
        return DiscoveredCamera(
            external_id=cid,
            name=row.get("name") or f"Grid {cid.upper()}",
            rtsp_url=row.get("rtsp") or row.get("rtsp_url") or f"{settings.grid_rtsp_base}/{cid}",
            hls_url=row.get("hls") or row.get("hls_url") or
                    f"{settings.grid_hls_base}/live/stream/{cid}/index.m3u8",
            whep_url=row.get("whep") or f"{settings.grid_whep_base}/{cid}/whep",
            department=row.get("department") or "Police",
            location_name=row.get("location") or row.get("location_name") or "",
            latitude=float(row.get("lat") or row.get("latitude") or 0.0),
            longitude=float(row.get("lon") or row.get("lng") or row.get("longitude") or 0.0),
            codec=(row.get("codec") or "").upper(),
            resolution=row.get("resolution") or "",
            vendor=self.vendor,
            reachable=row.get("live") if isinstance(row.get("live"), bool) else None,
            extra={k: v for k, v in row.items() if k not in {"id", "name"}},
        )

    def _fallback(self, n: int) -> DiscoveredCamera:
        cid = f"cam{n:02d}"
        return DiscoveredCamera(
            external_id=cid,
            name=f"Grid {cid.upper()}",
            rtsp_url=f"{settings.grid_rtsp_base}/{cid}",
            hls_url=f"{settings.grid_hls_base}/live/stream/{cid}/index.m3u8",
            whep_url=f"{settings.grid_whep_base}/{cid}/whep",
            department="Police",
            vendor=self.vendor,
            extra={"source": "documented id range, catalogue unreachable"},
        )

    def probe(self, camera: DiscoveredCamera) -> bool | None:
        """TCP-connect to the RTSP port. Cheap liveness without opening a
        session, which matters because each real session costs the gateway a
        copy of the stream."""
        if not camera.rtsp_url:
            return None
        parsed = urlparse(camera.rtsp_url)
        host, port = parsed.hostname, parsed.port or 554
        if not host:
            return None
        try:
            with socket.create_connection((host, port), timeout=4):
                return True
        except OSError:
            return False
