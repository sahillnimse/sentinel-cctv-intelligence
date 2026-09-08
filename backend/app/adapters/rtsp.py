"""Generic RTSP adapter.

The lowest common denominator: a list of RTSP URLs configured by an operator,
for kit that speaks RTSP but offers no discovery, no catalogue and no SDK.
Most analog cameras behind a DVR land here, since the DVR exposes a channel
per camera at a vendor-specific path.

Configure with RTSP_SOURCES as comma-separated `name=url` pairs:

    RTSP_SOURCES=Gate 1=rtsp://10.0.0.4:554/ch1,Gate 2=rtsp://10.0.0.4:554/ch2
"""

import logging
import socket
from urllib.parse import urlparse

from ..config import settings
from .base import AdapterInfo, DiscoveredCamera

log = logging.getLogger("sentinel.adapters.rtsp")


def _parse_sources(raw: str) -> list[tuple[str, str]]:
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            name, url = chunk.split("=", 1)
        else:
            name, url = "", chunk
        url = url.strip()
        if not url:
            continue
        name = name.strip() or urlparse(url).path.strip("/").replace("/", "-") or "camera"
        out.append((name, url))
    return out


class GenericRtspAdapter:
    key = "rtsp"
    label = "Manually configured RTSP sources"
    vendor = "any RTSP device or DVR channel"
    protocols = ["RTSP"]

    def configured(self) -> bool:
        return bool(_parse_sources(settings.rtsp_sources))

    def info(self) -> AdapterInfo:
        sources = _parse_sources(settings.rtsp_sources)
        return AdapterInfo(
            self.key, self.label, self.vendor, self.protocols, bool(sources),
            f"{len(sources)} source(s) configured" if sources
            else "set RTSP_SOURCES as comma-separated name=url pairs")

    def discover(self) -> list[DiscoveredCamera]:
        return [
            DiscoveredCamera(
                external_id=f"rtsp-{i}",
                name=name,
                rtsp_url=url,
                department=settings.rtsp_default_department,
                camera_type="IP",
                vendor=self.vendor,
                extra={"configured_manually": True},
            )
            for i, (name, url) in enumerate(_parse_sources(settings.rtsp_sources), 1)
        ]

    def probe(self, camera: DiscoveredCamera) -> bool | None:
        parsed = urlparse(camera.rtsp_url)
        if not parsed.hostname:
            return None
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 554), timeout=4):
                return True
        except OSError:
            return False
