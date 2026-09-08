"""Contract for government database connectors.

The brief requires integration with VAHAN, SARTHI, eGujCop, AFIS and NAFIS.
Nobody issues live credentials for those to a hackathon team, so each
connector here is a deterministic mock that ships no real data and makes no
outbound calls. What matters is that the *contract* is real: a production
deployment replaces one method body with authenticated calls and everything
downstream — trace, alerts, copilot, dashboards — keeps working unchanged.

Same shape as the camera adapters in app/adapters, for the same reason. One
interface, many authorities, and adding a sixth is one module.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ConnectorInfo:
    key: str
    label: str
    authority: str
    kind: str                    # "vehicle" | "person" | "both"
    live: bool                   # True only when talking to the real service
    detail: str = ""
    fields: list[str] = field(default_factory=list)


@dataclass
class LookupResult:
    """One authority's answer about one subject.

    `found` false is a real answer, not an error — most plates are not on
    anybody's list, and the console needs to say so rather than show a blank.
    """

    connector: str
    subject: str
    found: bool
    record: dict = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)   # why this matters, if it does
    source: str = "mock"

    def as_dict(self) -> dict:
        return {
            "connector": self.connector, "subject": self.subject,
            "found": self.found, "record": self.record,
            "alerts": self.alerts, "source": self.source,
        }


@runtime_checkable
class Connector(Protocol):
    key: str
    label: str
    authority: str
    kind: str

    def configured(self) -> bool:
        """True when this connector can answer at all."""

    def info(self) -> ConnectorInfo:
        ...

    def lookup_vehicle(self, plate: str) -> LookupResult | None:
        """Answer about a vehicle, or None if this authority has no view of vehicles."""

    def lookup_person(self, reference: str) -> LookupResult | None:
        """Answer about a person, or None if this authority has no view of people."""
