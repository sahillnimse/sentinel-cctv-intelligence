"""Edge tier: local spooling so a node keeps working without an uplink.

Disabled by default. A node becomes an edge node by setting EDGE_MODE=true and
EDGE_CENTRAL_URL to the central tier; the same codebase then runs as either a
central server or a district node, which is the point of the architecture.
"""

import json
import logging
import urllib.error
import urllib.request

from ..config import settings
from .spool import Forwarder, Spool

log = logging.getLogger("sentinel.edge")

_spool: Spool | None = None
_forwarder: Forwarder | None = None


def get_spool() -> Spool | None:
    return _spool


def get_forwarder() -> Forwarder | None:
    return _forwarder


def enabled() -> bool:
    return settings.edge_mode


def record(kind: str, payload: dict) -> bool:
    """Queue an event for the centre. Returns False when not in edge mode, so
    the caller writes locally as usual."""
    if _spool is None:
        return False
    _spool.put(kind, payload)
    return True


def _post_batch(rows) -> bool:
    """Ship a batch to the centre. True only on an accepted response."""
    events = [payload for _, _, payload in rows]
    body = json.dumps({"node_id": settings.edge_node_id, "events": events},
                      default=str).encode()
    req = urllib.request.Request(
        settings.edge_central_url.rstrip("/") + "/api/edge/ingest",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    if settings.edge_token:
        req.add_header("Authorization", f"Bearer {settings.edge_token}")
    try:
        with urllib.request.urlopen(req, timeout=settings.edge_timeout_s) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.debug("uplink unavailable: %s", exc)
        return False


def start() -> None:
    global _spool, _forwarder
    if not settings.edge_mode or _spool is not None:
        return
    _spool = Spool(settings.edge_spool_path, max_rows=settings.edge_spool_max_rows)
    log.info("edge mode on, spooling to %s", _spool.path)
    if settings.edge_central_url:
        _forwarder = Forwarder(_spool, _post_batch)
        _forwarder.start()
        log.info("forwarding to %s", settings.edge_central_url)
    else:
        log.warning("edge mode on but EDGE_CENTRAL_URL unset — spooling only")


def stop() -> None:
    global _spool, _forwarder
    if _forwarder is not None:
        _forwarder.stop_event.set()
        _forwarder = None
    if _spool is not None:
        _spool.close()
        _spool = None
