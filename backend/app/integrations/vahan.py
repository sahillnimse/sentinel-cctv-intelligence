"""VAHAN and SARTHI connector.

Wraps the existing mock in app/routers/vahan.py rather than duplicating it, so
there is one implementation of the vehicle-registry mock and the router keeps
working unchanged. See that module for the integration contract.
"""

from ..utils.plates import normalize
from .base import ConnectorInfo, LookupResult

# rc_status values that an operator needs told about, not just shown.
ACTIONABLE = {"STOLEN", "BLACKLISTED", "EXPIRED"}


class VahanConnector:
    key = "vahan"
    label = "VAHAN / SARTHI"
    authority = "MoRTH, Government of India"
    kind = "vehicle"

    def configured(self) -> bool:
        return True

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            self.key, self.label, self.authority, self.kind, live=False,
            detail="deterministic mock — production calls the Parivahan NIC "
                   "endpoints or a state-authorised RC-verification vendor",
            fields=["owner_name", "rc_status", "make", "model", "color",
                    "vehicle_class", "fuel", "registered_rto"],
        )

    def lookup_vehicle(self, plate: str) -> LookupResult:
        subject = normalize(plate)
        if not subject:
            return LookupResult(self.key, plate, found=False)

        from ..routers.vahan import enrich
        record = enrich(subject) or {}
        if not record:
            return LookupResult(self.key, subject, found=False)

        status = str(record.get("rc_status", "")).upper()
        alerts = []
        if status in ACTIONABLE:
            alerts.append(f"RC status {status}")
        return LookupResult(self.key, subject, found=True, record=record, alerts=alerts)

    def lookup_person(self, reference: str) -> None:
        return None   # SARTHI is licence-holder data, not a person-of-interest index
