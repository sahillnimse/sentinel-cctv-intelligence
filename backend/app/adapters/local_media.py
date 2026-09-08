"""Local media adapter — a second, structurally different federated system.

Points at a directory of video files and presents each one as a camera. Two
reasons it exists rather than being a test fixture:

1. Model 3 requires federating at least two different systems. This is a
   genuinely different source: files on disk with no gateway, no catalogue API
   and no network protocol, reached by a completely different code path from
   the RTSP grid. If the federation layer can carry both, the adapter contract
   is doing real work.

2. It is how a department with exported DVR footage, or an investigator with a
   seized recording, gets that material analysed by the same pipeline.

OpenCV reads the file directly, so no streaming server is needed. Files loop,
matching the grid's own looping behaviour.
"""

import logging
from pathlib import Path

from ..config import settings
from .base import AdapterInfo, DiscoveredCamera

log = logging.getLogger("sentinel.adapters.local")

VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".ts"}


class LocalMediaAdapter:
    key = "local-media"
    label = "Local media library"
    vendor = "file-backed (exported DVR / seized media)"
    protocols = ["file"]

    def _root(self) -> Path | None:
        raw = settings.local_media_dir
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_dir() else None

    def configured(self) -> bool:
        return self._root() is not None

    def info(self) -> AdapterInfo:
        root = self._root()
        if root is None:
            return AdapterInfo(
                self.key, self.label, self.vendor, self.protocols, False,
                f"set LOCAL_MEDIA_DIR to a folder of video files "
                f"(currently {settings.local_media_dir or 'unset'})")
        n = len(self._files(root))
        return AdapterInfo(self.key, self.label, self.vendor, self.protocols,
                           True, f"{n} file(s) under {root}")

    def _files(self, root: Path) -> list[Path]:
        return sorted(p for p in root.rglob("*")
                      if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)

    def discover(self) -> list[DiscoveredCamera]:
        root = self._root()
        if root is None:
            return []
        out = []
        for i, path in enumerate(self._files(root), 1):
            stem = path.stem
            out.append(DiscoveredCamera(
                external_id=f"file-{stem}"[:50],
                name=f"File {stem}",
                # OpenCV opens a plain path; the worker treats it like any
                # other source, so nothing downstream needs to know.
                rtsp_url=str(path.resolve()),
                department=settings.local_media_department,
                camera_type="File",
                location_name=str(path.parent.name),
                vendor=self.vendor,
                reachable=True,
                extra={"size_bytes": path.stat().st_size, "index": i},
            ))
        return out

    def probe(self, camera: DiscoveredCamera) -> bool | None:
        if not camera.rtsp_url:
            return None
        return Path(camera.rtsp_url).exists()
