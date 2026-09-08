"""Adapter registry.

Adding a vendor means writing one module and registering it here. Nothing else
in the platform changes, which is the vendor-lock-in answer the brief asks for.
"""

import logging

from .base import Adapter, AdapterInfo, DiscoveredCamera
from .local_media import LocalMediaAdapter
from .onvif import OnvifAdapter
from .rtsp import GenericRtspAdapter
from .sentinel_grid import SentinelGridAdapter

log = logging.getLogger("sentinel.adapters")

_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    _REGISTRY[adapter.key] = adapter


for _a in (SentinelGridAdapter(), OnvifAdapter(), GenericRtspAdapter(),
           LocalMediaAdapter()):
    register(_a)


def all_adapters() -> list[Adapter]:
    return list(_REGISTRY.values())


def get(key: str) -> Adapter | None:
    return _REGISTRY.get(key)


def describe() -> list[dict]:
    out = []
    for a in all_adapters():
        try:
            i = a.info()
        except Exception as exc:           # a broken adapter must not hide the rest
            log.exception("adapter %s failed to describe itself", a.key)
            i = AdapterInfo(a.key, a.label, a.vendor, a.protocols, False, str(exc))
        out.append({
            "key": i.key, "label": i.label, "vendor": i.vendor,
            "protocols": i.protocols, "configured": i.configured, "detail": i.detail,
        })
    return out


def discover(key: str) -> list[DiscoveredCamera]:
    adapter = get(key)
    if adapter is None:
        raise KeyError(key)
    return adapter.discover()


__all__ = ["Adapter", "AdapterInfo", "DiscoveredCamera", "all_adapters",
           "describe", "discover", "get", "register"]
