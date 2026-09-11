from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CameraIn(BaseModel):
    name: str
    department: str = "Police"
    camera_type: str = "IP"
    rtsp_url: str = ""
    hls_url: str = ""
    external_id: str = ""
    latitude: float = 23.2156
    longitude: float = 72.6369
    location_name: str = ""
    analytics_enabled: bool = True
    heading: float = 0.0
    fov_deg: float = 55.0
    range_m: float = 80.0


class CameraOut(CameraIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    last_seen: Optional[datetime] = None


class SightingIn(BaseModel):
    camera_id: int
    plate: str
    confidence: float = 1.0
    ts: Optional[datetime] = None


class SightingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    plate: str
    plate_raw: str
    confidence: float
    ts: datetime
    pts_ms: float
    snapshot: str


class RoutePoint(BaseModel):
    sighting_id: int
    camera_id: int
    camera_name: str
    location_name: str
    latitude: float
    longitude: float
    plate: str
    confidence: float
    ts: datetime
    snapshot: str
    # spatio-temporal validation (from camgraph)
    gap_km: float = 0.0
    gap_s: float = 0.0
    speed_kmph: float = 0.0
    flagged: bool = False
    reason: str = ""


class TraceResult(BaseModel):
    """Unified trace payload: route + validation summary + VAHAN enrichment +
    watchlist status — everything the demo needs in one response."""
    plate: str
    route: list[RoutePoint]
    summary: dict = {}
    vahan: dict = {}
    watchlisted: bool = False
    watchlist_reason: str = ""
    # One entry per government authority queried (VAHAN, eGujCop, ...).
    registry: list[dict] = []
    # Flattened reasons this vehicle matters, from any authority.
    registry_alerts: list[str] = []


class WatchlistIn(BaseModel):
    plate: str
    label: str = ""
    reason: str = "stolen"
    active: bool = True


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate: str = ""
    label: str = ""
    reason: str = "stolen"
    active: bool = True
    kind: str = "vehicle"
    photo: str = ""
    created_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sighting_id: int
    watchlist_id: int
    camera_id: int
    plate: str
    ts: datetime
    acknowledged: bool


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "viewer"


# --- user administration ----------------------------------------------------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    full_name: str = ""
    badge_no: str = ""
    active: bool = True
    must_change_password: bool = False
    created_at: datetime
    created_by: str = ""
    last_login_at: datetime | None = None
    # Deliberately no password_hash. A response model is the last place that
    # can leak one, and "it is only a hash" is not a reason to ship it.


class UserCreate(BaseModel):
    username: str
    role: str = "viewer"
    full_name: str = ""
    badge_no: str = ""
    # Optional: omit it and the server generates a temporary one, which is the
    # safer default because it is never typed, mailed or reused from elsewhere.
    password: str | None = None


class UserUpdate(BaseModel):
    """Every field optional — a PATCH changes only what it names."""
    role: str | None = None
    full_name: str | None = None
    badge_no: str | None = None
    active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class TempPasswordOut(BaseModel):
    """Returned once, on create or reset. Never retrievable afterwards."""
    user: UserOut
    temporary_password: str
    note: str = ("Shown once. The account must change it at next sign-in.")
