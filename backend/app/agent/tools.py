"""Tools the SENTINEL copilot can call.

Each tool is a plain function taking a DB session + kwargs and returning a
JSON-serializable dict. TOOL_SCHEMAS is the OpenAI/OpenRouter function spec.
The agent loop dispatches by name via TOOL_IMPL.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Alert, Camera, Sighting, WatchlistEntry
from ..utils.plates import normalize, plates_match


def list_cameras(db: Session, department: str | None = None, status: str | None = None):
    q = db.query(Camera)
    if department:
        q = q.filter(Camera.department == department)
    if status:
        q = q.filter(Camera.status == status)
    cams = q.order_by(Camera.id).all()
    return {
        "count": len(cams),
        "cameras": [
            {"id": c.id, "name": c.name, "department": c.department,
             "location": c.location_name, "status": c.status,
             "lat": c.latitude, "lon": c.longitude}
            for c in cams
        ],
    }


def trace_vehicle(db: Session, plate: str, fuzzy: bool = True):
    target = normalize(plate)
    q = db.query(Sighting).join(Camera).order_by(Sighting.ts)
    rows = q.all()
    if fuzzy:
        rows = [s for s in rows if plates_match(s.plate, target)]
    else:
        rows = [s for s in rows if s.plate == target]
    return {
        "plate": target,
        "sighting_count": len(rows),
        "route": [
            {"camera": s.camera.name, "location": s.camera.location_name,
             "lat": s.camera.latitude, "lon": s.camera.longitude,
             "ts": s.ts.isoformat(), "read": s.plate,
             "confidence": round(s.confidence, 2)}
            for s in rows
        ],
    }


def recent_sightings(db: Session, minutes: int = 60, limit: int = 40, camera_id: int | None = None):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    q = db.query(Sighting).join(Camera).filter(Sighting.ts >= since)
    if camera_id:
        q = q.filter(Sighting.camera_id == camera_id)
    rows = q.order_by(Sighting.ts.desc()).limit(min(limit, 200)).all()
    return {
        "window_minutes": minutes, "count": len(rows),
        "sightings": [
            {"plate": s.plate, "camera": s.camera.name,
             "location": s.camera.location_name, "ts": s.ts.isoformat(),
             "confidence": round(s.confidence, 2)}
            for s in rows
        ],
    }


def search_plate(db: Session, query: str, limit: int = 25):
    """Substring/fuzzy plate lookup across all sightings."""
    q = normalize(query)
    rows = db.query(Sighting).join(Camera).order_by(Sighting.ts.desc()).all()
    hits = [s for s in rows if q in s.plate or plates_match(s.plate, q, max_dist=2)]
    hits = hits[:limit]
    return {
        "query": q, "count": len(hits),
        "results": [
            {"plate": s.plate, "camera": s.camera.name, "ts": s.ts.isoformat(),
             "confidence": round(s.confidence, 2)}
            for s in hits
        ],
    }


def add_to_watchlist(db: Session, plate: str, reason: str = "wanted", label: str = ""):
    entry = WatchlistEntry(plate=normalize(plate), reason=reason, label=label)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"added": True, "id": entry.id, "plate": entry.plate, "reason": entry.reason}


def list_alerts(db: Session, unacknowledged_only: bool = False, limit: int = 30):
    q = db.query(Alert).join(Camera)
    if unacknowledged_only:
        q = q.filter(Alert.acknowledged.is_(False))
    rows = q.order_by(Alert.ts.desc()).limit(min(limit, 200)).all()
    return {
        "count": len(rows),
        "alerts": [
            {"id": a.id, "plate": a.plate, "camera": a.camera.name,
             "ts": a.ts.isoformat(), "acknowledged": a.acknowledged}
            for a in rows
        ],
    }


def system_stats(db: Session):
    total_cams = db.query(func.count(Camera.id)).scalar()
    online = db.query(func.count(Camera.id)).filter(Camera.status == "online").scalar()
    total_sightings = db.query(func.count(Sighting.id)).scalar()
    total_alerts = db.query(func.count(Alert.id)).scalar()
    watchlist = db.query(func.count(WatchlistEntry.id)).scalar()
    top = (db.query(Camera.name, func.count(Sighting.id).label("n"))
           .join(Sighting, Sighting.camera_id == Camera.id)
           .group_by(Camera.id).order_by(func.count(Sighting.id).desc()).limit(5).all())
    return {
        "cameras_total": total_cams, "cameras_online": online,
        "sightings_total": total_sightings, "alerts_total": total_alerts,
        "watchlist_size": watchlist,
        "busiest_cameras": [{"camera": n, "sightings": c} for n, c in top],
    }


TOOL_IMPL = {
    "list_cameras": list_cameras,
    "trace_vehicle": trace_vehicle,
    "recent_sightings": recent_sightings,
    "search_plate": search_plate,
    "add_to_watchlist": add_to_watchlist,
    "list_alerts": list_alerts,
    "system_stats": system_stats,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "system_stats",
        "description": "Overall system status: camera counts, total sightings/alerts, watchlist size, busiest cameras. Call this first for 'how are things' / 'status' questions.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_cameras",
        "description": "List cameras, optionally filtered by department or status (online/offline).",
        "parameters": {"type": "object", "properties": {
            "department": {"type": "string"},
            "status": {"type": "string", "enum": ["online", "offline", "unknown"]},
        }},
    }},
    {"type": "function", "function": {
        "name": "trace_vehicle",
        "description": "Reconstruct a vehicle's route across cameras from its registration number. Returns timestamped, location-wise movement history. This is the core investigative tool.",
        "parameters": {"type": "object", "properties": {
            "plate": {"type": "string", "description": "Registration number, e.g. GJ01AB1234"},
            "fuzzy": {"type": "boolean", "description": "Tolerate OCR misreads (default true)"},
        }, "required": ["plate"]},
    }},
    {"type": "function", "function": {
        "name": "recent_sightings",
        "description": "Recent plate detections within the last N minutes, optionally for one camera.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer"}, "limit": {"type": "integer"},
            "camera_id": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "search_plate",
        "description": "Find sightings whose plate matches a partial or noisy query (substring or fuzzy).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "add_to_watchlist",
        "description": "Add a vehicle to the watchlist so any future sighting raises an alert. Confirm the plate with the user before calling if ambiguous.",
        "parameters": {"type": "object", "properties": {
            "plate": {"type": "string"},
            "reason": {"type": "string", "enum": ["stolen", "wanted", "blacklisted", "missing"]},
            "label": {"type": "string"},
        }, "required": ["plate"]},
    }},
    {"type": "function", "function": {
        "name": "list_alerts",
        "description": "List watchlist alerts, optionally only unacknowledged ones.",
        "parameters": {"type": "object", "properties": {
            "unacknowledged_only": {"type": "boolean"}, "limit": {"type": "integer"},
        }},
    }},
]
