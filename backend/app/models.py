from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, LargeBinary,
                        String, Text, and_, or_)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(100), default="Police")
    camera_type: Mapped[str] = mapped_column(String(50), default="IP")
    rtsp_url: Mapped[str] = mapped_column(Text, default="")
    hls_url: Mapped[str] = mapped_column(Text, default="")
    external_id: Mapped[str] = mapped_column(String(50), default="", index=True)  # grid camera id, e.g. cam04
    latitude: Mapped[float] = mapped_column(Float, default=23.2156)
    longitude: Mapped[float] = mapped_column(Float, default=72.6369)
    location_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="unknown")  # online | offline | unknown
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # geospatial orientation for the 3D overview + vehicle localization
    heading: Mapped[float] = mapped_column(Float, default=0.0)     # compass bearing the camera faces (deg)
    fov_deg: Mapped[float] = mapped_column(Float, default=55.0)    # horizontal field of view (deg)
    range_m: Mapped[float] = mapped_column(Float, default=80.0)    # nominal ground range (metres)

    sightings: Mapped[list["Sighting"]] = relationship(back_populates="camera")


def has_stream():
    """SQL predicate for cameras the ingestion worker can actually open.

    CameraWorker tries rtsp_url first and falls back to hls_url, so selecting
    on rtsp_url alone silently excludes HLS-only cameras from autostart and
    from Start All. They then sit on the live wall as permanently idle tiles
    with no explanation. Both call sites use this instead.
    """
    return or_(and_(Camera.rtsp_url.isnot(None), Camera.rtsp_url != ""),
               and_(Camera.hls_url.isnot(None), Camera.hls_url != ""))


class Sighting(Base):
    __tablename__ = "sightings"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    plate: Mapped[str] = mapped_column(String(20), index=True)  # normalized
    plate_raw: Mapped[str] = mapped_column(String(30), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    pts_ms: Mapped[float] = mapped_column(Float, default=0.0)  # stream presentation timestamp
    snapshot: Mapped[str] = mapped_column(String(300), default="")  # relative path under /snapshots
    sha256: Mapped[str] = mapped_column(String(64), default="")  # capture-time hash for evidence chain

    camera: Mapped[Camera] = relationship(back_populates="sightings")


class VehicleDetection(Base):
    """Every vehicle the cascade detects, with its best-effort plate (may be
    empty if unreadable). This is the raw vehicle log; Sighting is the subset
    with a confident plate read."""

    __tablename__ = "vehicle_detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    vehicle_type: Mapped[str] = mapped_column(String(20), default="vehicle")  # car|motorcycle|bus|truck
    plate: Mapped[str] = mapped_column(String(20), default="", index=True)     # normalized, may be ""
    plate_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    snapshot: Mapped[str] = mapped_column(String(300), default="")
    # normalized image position of the vehicle's ground contact (bbox bottom-centre),
    # used to project the detection to a geo-coordinate for the 3D map
    img_x: Mapped[float] = mapped_column(Float, default=0.5)  # 0=left .. 1=right
    img_y: Mapped[float] = mapped_column(Float, default=0.9)  # 0=top .. 1=bottom (near)
    sha256: Mapped[str] = mapped_column(String(64), default="")  # capture-time evidence hash


class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(String(20), index=True, default="")  # normalized (vehicles)
    label: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(String(50), default="stolen")  # stolen | wanted | blacklisted | missing
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # person watchlist (wanted / missing persons) — face recognition
    kind: Mapped[str] = mapped_column(String(20), default="vehicle")  # vehicle | person
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)  # 512-d face emb
    photo: Mapped[str] = mapped_column(String(300), default="")  # enrollment snapshot filename


class AuditLog(Base):
    """Append-only record of every mutating API call. Required for an
    evidentiary chain: who changed the watchlist, who started analytics on
    which camera, who acknowledged which alert."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    username: Mapped[str] = mapped_column(String(100), default="", index=True)
    role: Mapped[str] = mapped_column(String(20), default="")
    action: Mapped[str] = mapped_column(String(10), default="")   # HTTP method
    target: Mapped[str] = mapped_column(String(300), default="")  # request path
    status: Mapped[int] = mapped_column(default=0)                # response code
    detail: Mapped[str] = mapped_column(Text, default="")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    sighting_id: Mapped[int] = mapped_column(ForeignKey("sightings.id"))
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlist.id"))
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    plate: Mapped[str] = mapped_column(String(20), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
