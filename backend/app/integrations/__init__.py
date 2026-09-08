"""Government database connector registry.

Adding a sixth authority is one module and one line here. Every connector is
a deterministic mock — see each module's integration contract for what a
production deployment replaces.
"""

import logging

from .base import Connector, ConnectorInfo, LookupResult
from .biometric import AfisConnector, NafisConnector
from .egujcop import EGujCopConnector
from .vahan import VahanConnector

log = logging.getLogger("sentinel.integrations")

_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    _REGISTRY[connector.key] = connector


for _c in (VahanConnector(), EGujCopConnector(), AfisConnector(), NafisConnector()):
    register(_c)


def all_connectors() -> list[Connector]:
    return list(_REGISTRY.values())


def get(key: str) -> Connector | None:
    return _REGISTRY.get(key)


def describe() -> list[dict]:
    out = []
    for c in all_connectors():
        try:
            i = c.info()
        except Exception as exc:
            log.exception("connector %s failed to describe itself", c.key)
            i = ConnectorInfo(c.key, c.label, c.authority, c.kind, False, str(exc))
        out.append({"key": i.key, "label": i.label, "authority": i.authority,
                    "kind": i.kind, "live": i.live, "detail": i.detail,
                    "fields": i.fields})
    return out


def _fan_out(method: str, subject: str) -> list[dict]:
    """Ask every connector that has a view of this subject type.

    One authority being down must not take the others with it — an
    investigator is better served by four answers and one error than by
    nothing at all.
    """
    results = []
    for c in all_connectors():
        try:
            if not c.configured():
                continue
            result = getattr(c, method)(subject)
            if result is not None:
                results.append(result.as_dict())
        except Exception as exc:
            log.exception("%s failed on %s", c.key, method)
            results.append({"connector": c.key, "subject": subject, "found": False,
                            "record": {}, "alerts": [], "source": "error",
                            "error": str(exc)})
    return results


def lookup_vehicle(plate: str) -> list[dict]:
    return _fan_out("lookup_vehicle", plate)


def lookup_person(reference: str) -> list[dict]:
    return _fan_out("lookup_person", reference)


__all__ = ["Connector", "ConnectorInfo", "LookupResult", "all_connectors",
           "describe", "get", "lookup_person", "lookup_vehicle", "register"]
