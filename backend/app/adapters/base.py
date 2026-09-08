"""Adapter contract for federating heterogeneous camera systems.

Every departmental system — an ONVIF IP camera, an analog camera behind a DVR,
a Hikvision NVR, a Milestone or Genetec VMS, the Sentinel sandbox grid — is
reached through one of these. The rest of the platform only ever sees
`DiscoveredCamera` and a stream URL, so onboarding a new vendor means writing
one adapter rather than touching the registry, the workers or the console.

That is the whole point of Model 3: departments keep their own infrastructure,
and the federation layer speaks to each of them in its own dialect.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class DiscoveredCamera:
    """What an adapter can tell us about one camera before it is onboarded."""

    external_id: str
    name: str
    rtsp_url: str = ""
    hls_url: str = ""
    whep_url: str = ""
    department: str = ""
    camera_type: str = "IP"
    location_name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    codec: str = ""
    resolution: str = ""
    vendor: str = ""
    reachable: bool | None = None      # None = not probed
    extra: dict = field(default_factory=dict)

    def as_camera_fields(self) -> dict:
        """Map onto the Camera model's columns."""
        return {
            "external_id": self.external_id,
            "name": self.name,
            "rtsp_url": self.rtsp_url,
            "hls_url": self.hls_url,
            "department": self.department or "Unassigned",
            "camera_type": self.camera_type,
            "location_name": self.location_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


@dataclass
class AdapterInfo:
    key: str
    label: str
    vendor: str
    protocols: list[str]
    configured: bool
    detail: str = ""


@runtime_checkable
class Adapter(Protocol):
    """A source of cameras.

    Adapters are deliberately small. `discover` is the only method that has to
    do real work; `probe` is optional connectivity checking and defaults to
    "unknown" so an adapter for a system that cannot be probed cheaply is still
    a valid adapter.
    """

    key: str
    label: str
    vendor: str
    protocols: list[str]

    def configured(self) -> bool:
        """True when this adapter has what it needs to run (URL, credentials)."""

    def info(self) -> AdapterInfo:
        ...

    def discover(self) -> list[DiscoveredCamera]:
        """Enumerate cameras this system exposes."""

    def probe(self, camera: DiscoveredCamera) -> bool | None:
        """Check whether a camera is currently reachable. None = unknown."""
