"""Court-admissible evidence export for a traced vehicle.

Given a plate, SENTINEL can reconstruct the vehicle's movement across the
CCTV grid. This router turns that reconstruction into artifacts an
investigating officer can file: a plain CSV of every timestamped sighting
(with a SHA-256 hash of each snapshot so tampering is detectable), and a
formatted PDF "Vehicle Movement Evidence Report" with a VAHAN registration
block, embedded snapshot thumbnails, a chain-of-custody statement, and
officer signature blocks.

Determinism note: the report must be reproducible from the same database
state, so timestamps in the document come from the sighting data itself
(the ``generated_at`` query param defaults to the latest sighting), never
from ``datetime.now()``.
"""

import csv
import hashlib
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..db import get_db
from ..models import Sighting
from ..utils.plates import normalize, plates_match

router = APIRouter(prefix="/evidence", tags=["evidence"])


# --- module-level helpers ---------------------------------------------------

def file_sha256(filename: str | None) -> str:
    """SHA-256 hex digest of a snapshot file under settings.snapshot_dir.

    Returns '' when the filename is empty or the file does not exist, so the
    evidence row is still emitted (absence of a hash is itself informative).
    """
    if not filename:
        return ""
    path = settings.snapshot_dir / filename
    try:
        if not path.is_file():
            return ""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def fetch_sightings(db: Session, plate: str) -> tuple[str, list[Sighting]]:
    """Return (normalized_plate, sightings) for a plate, fuzzy-matched over
    every sighting and ordered chronologically. Camera is eager-loaded so the
    export does not issue a query per row."""
    target = normalize(plate)
    if not target:
        return target, []
    rows = (
        db.query(Sighting)
        .options(joinedload(Sighting.camera))
        .order_by(Sighting.ts)
        .all()
    )
    matched = [s for s in rows if plates_match(s.plate, target)]
    return target, matched


def _report_timestamp(sightings: list[Sighting], generated_at: str | None) -> datetime:
    """Resolve the report generation time deterministically. Explicit ISO
    param wins; otherwise the latest sighting ts (data-derived, reproducible)."""
    if generated_at:
        try:
            return datetime.fromisoformat(generated_at)
        except ValueError:
            pass
    return max((s.ts for s in sightings), default=datetime.utcnow())


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d %H:%M:%S UTC")


# --- CSV export -------------------------------------------------------------

@router.get("/route/{plate}.csv")
def route_csv(plate: str, db: Session = Depends(get_db)):
    """Movement history as CSV with per-snapshot SHA-256 for integrity."""
    target, sightings = fetch_sightings(db, plate)
    if not sightings:
        raise HTTPException(404, "No sightings for this plate")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "seq", "timestamp_utc", "camera_id", "camera_name", "location",
        "latitude", "longitude", "plate_read", "confidence", "snapshot_sha256",
    ])
    for i, s in enumerate(sightings, 1):
        cam = s.camera
        w.writerow([
            i,
            _fmt_ts(s.ts),
            s.camera_id,
            cam.name if cam else "",
            cam.location_name if cam else "",
            cam.latitude if cam else "",
            cam.longitude if cam else "",
            s.plate,
            f"{s.confidence:.3f}" if s.confidence is not None else "",
            file_sha256(s.snapshot),
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="route_{target}.csv"'
        },
    )


# --- PDF export -------------------------------------------------------------

def _vahan_block(plate: str) -> dict:
    """Best-effort VAHAN enrichment; never fails the report if unavailable."""
    try:
        from ..routers.vahan import enrich  # lazy: optional sibling router
    except Exception:
        return {}
    try:
        data = enrich(plate)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@router.get("/route/{plate}.pdf")
def route_pdf(
    plate: str,
    generated_at: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Court-style Vehicle Movement Evidence Report as a PDF."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "PDF export requires reportlab. Install it with: "
                          "pip install reportlab",
            },
        )

    target, sightings = fetch_sightings(db, plate)
    if not sightings:
        raise HTTPException(404, "No sightings for this plate")

    report_ts = _report_timestamp(sightings, generated_at)
    vahan = _vahan_block(target)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "SentinelTitle", parent=styles["Title"], fontSize=16, spaceAfter=4,
        textColor=colors.HexColor("#0b1f4d"),
    ))
    styles.add(ParagraphStyle(
        "Org", parent=styles["Normal"], fontSize=10, alignment=1,
        textColor=colors.HexColor("#333333"),
    ))
    styles.add(ParagraphStyle(
        "SectionHead", parent=styles["Heading2"], fontSize=11,
        spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#0b1f4d"),
    ))
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7.5, leading=9)
    body = styles["Normal"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"SENTINEL Evidence Report {target}",
    )
    flow = []

    # --- Header
    flow.append(Paragraph("GUJARAT POLICE", styles["Org"]))
    flow.append(Paragraph("State Crime Records Bureau", styles["Org"]))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("SENTINEL &mdash; Vehicle Movement Evidence Report",
                          styles["SentinelTitle"]))
    flow.append(Spacer(1, 4))

    first_ts, last_ts = sightings[0].ts, sightings[-1].ts
    meta = [
        ["Vehicle Registration No.", target],
        ["Total Sightings", str(len(sightings))],
        ["Observation Window",
         f"{_fmt_ts(first_ts)}  →  {_fmt_ts(last_ts)}"],
        ["Report Generated", _fmt_ts(report_ts)],
    ]
    meta_tbl = Table(meta, colWidths=[55 * mm, 105 * mm])
    meta_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
    ]))
    flow.append(meta_tbl)

    # --- VAHAN block
    flow.append(Paragraph("Vehicle Registration Particulars (VAHAN)",
                          styles["SectionHead"]))
    if vahan:
        pref = ["owner_name", "owner", "reg_date", "registration_date",
                "maker", "make", "model", "vehicle_class", "fuel", "fuel_type",
                "chassis_no", "engine_no", "rc_status", "state", "rto"]
        seen, rows = set(), []
        for key in pref:
            if key in vahan and vahan[key] not in (None, ""):
                rows.append([key.replace("_", " ").title(), str(vahan[key])])
                seen.add(key)
        for key, val in vahan.items():
            if key not in seen and val not in (None, "") and not isinstance(val, (dict, list)):
                rows.append([str(key).replace("_", " ").title(), str(val)])
        if rows:
            vt = Table(rows, colWidths=[55 * mm, 105 * mm])
            vt.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e0e0e0")),
            ]))
            flow.append(vt)
        else:
            flow.append(Paragraph("No registration particulars available.", body))
    else:
        flow.append(Paragraph(
            "VAHAN registration data unavailable at time of report generation.",
            body))

    # --- Sightings table
    flow.append(Paragraph("Chronological Sighting Log", styles["SectionHead"]))
    header = ["#", "Timestamp (UTC)", "Camera", "Location", "Lat, Lon",
              "Conf.", "Snapshot SHA-256"]
    data = [[Paragraph(f"<b>{h}</b>", small) for h in header]]
    for i, s in enumerate(sightings, 1):
        cam = s.camera
        latlon = ""
        if cam and cam.latitude is not None and cam.longitude is not None:
            latlon = f"{cam.latitude:.5f}, {cam.longitude:.5f}"
        h = file_sha256(s.snapshot)
        h_disp = (h[:16] + "…") if h else "—"
        conf = f"{s.confidence:.2f}" if s.confidence is not None else ""
        data.append([
            Paragraph(str(i), small),
            Paragraph(_fmt_ts(s.ts), small),
            Paragraph(cam.name if cam else "?", small),
            Paragraph((cam.location_name if cam else "") or "", small),
            Paragraph(latlon, small),
            Paragraph(conf, small),
            Paragraph(h_disp, small),
        ])
    log_tbl = Table(
        data,
        colWidths=[7 * mm, 30 * mm, 30 * mm, 34 * mm, 26 * mm, 12 * mm, 35 * mm],
        repeatRows=1,
    )
    log_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b1f4d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f6fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(log_tbl)

    # --- Snapshot thumbnails (up to 6)
    thumbs = []
    for s in sightings:
        if not s.snapshot:
            continue
        p = settings.snapshot_dir / s.snapshot
        try:
            if p.is_file():
                thumbs.append((s, p))
        except OSError:
            continue
        if len(thumbs) >= 6:
            break

    if thumbs:
        flow.append(Paragraph("Snapshot Evidence", styles["SectionHead"]))
        cells, caps = [], []
        for s, p in thumbs:
            try:
                img = Image(str(p), width=52 * mm, height=39 * mm, kind="proportional")
            except Exception:
                continue
            cells.append(img)
            caps.append(Paragraph(
                f"{_fmt_ts(s.ts)}<br/>{s.camera.name if s.camera else '?'}", small))
        for start in range(0, len(cells), 3):
            row_imgs = cells[start:start + 3]
            row_caps = caps[start:start + 3]
            while len(row_imgs) < 3:
                row_imgs.append("")
                row_caps.append("")
            gt = Table([row_imgs, row_caps], colWidths=[56 * mm] * 3)
            gt.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ]))
            flow.append(gt)

    # --- Chain of custody
    flow.append(Paragraph("Chain of Custody", styles["SectionHead"]))
    coc = (
        "This report was generated automatically by the SENTINEL CCTV "
        "intelligence platform from digitally recorded and hashed evidence. "
        f"Each of the {len(sightings)} sighting records above corresponds to an "
        "automated number-plate recognition (ANPR) detection captured by a "
        "fixed CCTV camera in the Gujarat Police grid. The SHA-256 digest "
        "listed against each record is computed over the stored snapshot image "
        "at the time of export; any subsequent alteration of a snapshot will "
        "produce a different digest, rendering tampering detectable. The "
        "records are presented in strict chronological order and have not been "
        "edited, reordered, or filtered other than by the queried registration "
        "number. This document is reproducible from the source database and the "
        "stated generation timestamp."
    )
    flow.append(Paragraph(coc, body))

    # --- Signature blocks
    flow.append(Spacer(1, 18))
    sig = Table(
        [
            ["", ""],
            ["_______________________________", "_______________________________"],
            ["Investigating Officer", "Verifying Officer"],
            ["Name / Rank / Badge No.:", "Name / Rank / Badge No.:"],
            ["Signature & Date:", "Signature & Date:"],
        ],
        colWidths=[80 * mm, 80 * mm],
    )
    sig.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, 0), 20),
        ("TOPPADDING", (0, 3), (-1, -1), 8),
    ]))
    flow.append(sig)

    doc.build(flow)
    pdf = buf.getvalue()

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="route_{target}.pdf"'
        },
    )
