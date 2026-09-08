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
