# SENTINEL — Unified CCTV Intelligence Platform

Entry for the Gujarat Police Innovation Challenge 2026 (sentinel.gujarat.gov.in).

**Model 1 + Model 3.** A statewide camera registry with GIS mapping, which is
the compulsory foundation, plus a middleware federation layer that normalises
heterogeneous departmental systems onto one event interface. Departments keep
their own cameras, storage and retention.

The design decision everything else follows from: **move metadata, not video.**
Analytics runs at the edge or on a regional node and only compact structured
records travel to the centre. Video moves only when there is a hit worth
looking at.

Why that matters at scale: 80,000 cameras at 2 Mbps is roughly 160 Gbps of
sustained backhaul and about 52 PB at 30-day retention. The same network
carrying ANPR metadata instead is on the order of 16 GB a day.

---

## Running it

Two processes. No Docker required.

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

API docs at http://localhost:8000/docs

For plate recognition, also install the ML stack. Without it the server still
runs and workers do health monitoring only:

```bash
.venv\Scripts\pip install -r requirements-ml.txt
```

#### Running the models on an NVIDIA GPU

Optional. The cascade runs about twice as fast on a GPU, measured end to end on
a GTX 1650 against 1080p grid frames.

```bash
.venv\Scripts\pip uninstall -y onnxruntime
.venv\Scripts\pip install "onnxruntime-gpu[cuda,cudnn]"
```

Install one wheel or the other, never both: they provide the same `onnxruntime`
module and install order decides the winner. The extras pull the matching NVIDIA
runtime into the virtualenv, roughly 2 GB, so no system CUDA Toolkit is needed.
Check that `nvidia-smi` reports a driver at least as new as the CUDA version
your onnxruntime-gpu wants.

`INFERENCE_DEVICE` in `.env` selects `auto`, `cuda` or `cpu`, and governs the
ONNX models and the torch face engine together. `auto` is the default and only
uses the GPU after a probe actually executes a graph on it, because ONNX Runtime
advertises the CUDA provider whenever it was compiled with one, whether or not
the libraries load. `cuda` logs an error instead of degrading quietly. The
operations console and `/api/streams/status` report which device is live:

```
loaded on cuda:0 (ocr=awiros-indian, vehicle=onnx)
```

Measured on the GTX 1650, one worker, 1080p frames:

| device | median per frame | throughput |
|---|---|---|
| CPU | 1186 ms | 0.84 fps |
| CUDA | 523 ms | 1.91 fps |

Peak VRAM was 718 MB of 4096, so a 4 GB card has room. Set `CUDA_MEM_LIMIT_MB`
to bound the arena on a card also driving a display.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173, proxying `/api` and `/snapshots` to the backend.

Sign in with `admin` / `admin123` (see `.env.example` for the operator and
viewer accounts). The shipped passwords fail the password policy, so the first
sign-in forces a change before the console is usable — that gate is enforced by
the API, not just the login screen. Administrators then manage real accounts
(shifts of operators, viewers) under **Accounts & Access**, including revoking
access and issuing temporary passwords. Change the seed passwords and set a
real `JWT_SECRET` before any deployment.

### Tests

```bash
cd backend
.venv\Scripts\python -m pytest
```

266 tests covering plate matching, RBAC, credential redaction, account
administration with forced password changes, the edge spool, and the API end
to end.

---

## Architecture

```
Departmental systems          Edge / regional tier            Central tier
─────────────────────         ────────────────────            ────────────
DVR / NVR / VMS         →     adapter (ONVIF, RTSP,     →     PostGIS registry
(unchanged, in place)         vendor SDK, VMS API)            metadata index
                              decode → detect → ANPR          watchlist match
                              face, cross-camera track        alerting
                              SQLite spool if link down       GIS console
                                        │
                              metadata only ────────────────────┘
                              video stays local, pulled on a hit
```

### Backend layout

```
app/
  main.py            app wiring, RBAC + audit middleware, lifespan
  security.py        roles, tokens, audit helper
  config.py          settings, all env-overridable
  models.py          Camera, Sighting, VehicleDetection, Watchlist, Alert, AuditLog
  anpr/
    pipeline.py      vehicle-first cascade: detect → plate → OCR
    worker.py        one thread per camera; PTS timing, backoff, consensus voting
    awiros_ocr.py    Indian PP-OCRv5 ONNX recogniser
  face/engine.py     face detection and embedding for person watchlists
  edge/
    spool.py         durable SQLite queue + forwarder
  utils/
    plates.py        normalisation, fuzzy match, Indian-format coercion
    camgraph.py      haversine, spatio-temporal route validation
    geo.py           FOV projection for coverage polygons
  routers/           cameras, streams, sightings, watchlist, alerts, analytics,
                     evidence, vahan, fleet, edge, copilot, demo, auth
```

### Frontend

```
src/
  api.ts             typed client, token handling, reconnecting alert socket
  App.tsx            role-aware navigation, global alert toast
  pages/
    Dashboard        live counters, throughput, department status
    LiveWall         camera tiles from worker-published annotated frames
    Cameras          registry CRUD, bulk grid sync, Leaflet map
    Coverage         gap analysis grid, unhealthy camera report, CSV export
    Trace            plate search → route map, timeline, VAHAN, evidence export
    Detections       filterable detection log
    Analytics        throughput, vehicle mix, hourly pattern
    Fleet            NOC view: availability, analytics yield, worker state
    Alerts           watchlist hits and acknowledgement
    Audit            append-only record of every mutation
```

---

## Access control

Three roles, enforced by one middleware over every `/api` mutation rather than
per-route dependencies, so a router added later is protected by default.

| Role | Can |
|---|---|
| viewer | read dashboards, search, export |
| operator | + acknowledge alerts, start/stop analytics, edit the watchlist |
| admin | + camera registry changes, grid onboarding, demo controls |

Every mutating request is written to `audit_log` with the caller, the path and
the response code. Denials are recorded too, so a failed-permission pattern is
visible after the fact. Failed logins are recorded before the 401 returns.

---

## The Sentinel grid

Ingest is written against the published integrator guide. See
[docs/ingest-spec.md](docs/ingest-spec.md) for the full conformance checklist.
The points that break naive pipelines:

- **RTSP over TCP always.** UDP corrupts frames across NAT and looks like a
  model bug.
- **Timing from PTS, never arrival.** On connect the gateway replays its
  buffered GOP, so the first second arrives faster than real time. A tracker
  timestamping on arrival computes impossible velocities after every reconnect.
- **Declared frame rate is wrong.** Anything derived from `CAP_PROP_FPS` is
  garbage.
- **Feeds loop.** The scene cuts hard at the loop point; background models and
  track ids must survive it.
- **Mixed H.264/H.265 and mixed resolutions.** Per-camera properties come from
  the catalogue; a fixed-shape inference batch will not work.
- **Each client gets its own copy of the stream.** Open only what you process.

Grid access sits behind the portal login. Without a session cookie,
`sync-grid` falls back to the documented `cam01..cam30` range with placeholder
coordinates.

---

## Measured on this hardware

Development box: Ryzen 5 3550H, GTX 1650 4 GB, 6 GB usable RAM.

| What | Result |
|---|---|
| NVDEC decode, 1080p, realistic noisy content | ~555 fps aggregate, flat 8→16 streams |
| Software decode, same content | ~435 fps, and it costs all 8 CPU threads |
| AMF decode | unusable; `h264_amf` decode fails, use `d3d11va` |
| ANPR cascade, CPU | ~0.91 s/frame |

Reproduce with `tools/bench_decode.py` and `tools/bench_anpr.py`.

The ANPR figure is CPU-only — `onnxruntime` installs without a CUDA provider by
default. Raw single-frame OCR on grid footage is noisy: the plate prefix and
body stay stable while the last one or two characters drift, and the state code
occasionally flips. That is why the worker runs multi-frame Levenshtein
consensus voting with Indian-format positional coercion before confirming a
plate, and why watchlist matching is edit-distance tolerant rather than exact.

---

## Scaling out

Capacity settings are config, not code, so moving to stronger hardware is a
config change and a re-benchmark. See `config/system.yaml` and the edge
settings in `.env.example`.

An edge node runs the same codebase with `EDGE_MODE=true` and
`EDGE_CENTRAL_URL` pointed at the centre. Detections queue in a bounded SQLite
spool while the uplink is down and drain when it returns, at-least-once. A
district in Valsad or Dahod keeps detecting through an outage; only the
metadata is delayed.
