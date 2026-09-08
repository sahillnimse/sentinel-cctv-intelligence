from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from .. import ws
from ..db import get_db
from ..models import Alert
from ..schemas import AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(unacknowledged_only: bool = False, limit: int = 100,
                db: Session = Depends(get_db)):
    q = db.query(Alert)
    if unacknowledged_only:
        q = q.filter(Alert.acknowledged.is_(False))
    return q.order_by(Alert.ts.desc()).limit(min(limit, 1000)).all()


@router.post("/{alert_id}/ack", response_model=AlertOut)
def acknowledge(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    alert.acknowledged = True
    db.commit()
    db.refresh(alert)
    return alert


@router.websocket("/ws")
async def alerts_ws(websocket: WebSocket):
    """Live event stream: pushes 'sighting' and 'alert' events as JSON."""
    await ws.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive pings from client
    except WebSocketDisconnect:
        ws.disconnect(websocket)
