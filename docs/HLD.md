# SENTINEL — Technical Proposal and High-Level Design

**Unified CCTV Intelligence Platform**
Gujarat Police Innovation Challenge 2026

Models addressed: **Model 1** (Centralised CCTV Registry and GIS Foundation,
compulsory) combined with **Model 3** (VMS Federation and Middleware Layer), plus
the Model 4 analytics capabilities listed in section 4.5.

---

## 1. Executive summary

Gujarat operates roughly 80,000 cameras across departments that each own their
own recorders, vendor software, retention policy and budget. The footage exists.
A shared picture does not.

SENTINEL federates those estates rather than replacing them. Departments keep
their cameras, their storage and their control. The platform adds a statewide
registry with GIS mapping, a middleware layer that normalises every departmental
system onto one event interface, and edge analytics that turn video into
structured records beside the camera.

The single decision the architecture follows from is **move metadata, not
video**. Centralising 80,000 streams at 2 Mbps means 160 Gbps of sustained
backhaul and roughly 52 PB at 30-day retention. Carrying structured plate and
face records across the same network instead is on the order of 16 GB per day
statewide. Video moves only when a confirmed hit justifies pulling a clip.

What exists today is a working platform, not a concept: 76 API endpoints, 16
console screens, 4 federation adapters and 10 persisted data models, exercised
by an automated suite that runs on every change, and running as either an edge
node or the central server from one codebase.

---

## 2. Overall solution architecture

### 2.1 Tier diagram

```
 BAND 1 — DEPARTMENTS        BAND 2 — ADAPTERS      BAND 3 — EDGE NODE       BAND 4 — CENTRAL TIER
 (department-owned)          (federation)           (district / regional)    (state)

 Police DVR / NVR       -+                          +------------------+     +-------------------------+
 Municipal VMS          -|   +---------------+      | camera workers   |     | access + audit gate     |
 Transport cameras      -+-->| state grid    |----->| plate cascade    |     | metadata index (PostGIS)|
 Health / Panchayat     -|   | ONVIF         |      | face engine      |---->| trace + route validation|
 ONVIF IP cameras       -|   | manual RTSP   |      | watchlist match  | meta| alerts + evidence       |
 Recorded archive       -+   | file archive  |      | offline spool    | only| retention service       |
                             +---------------+      +------------------+     +-------------------------+
                                                            ^                            |
                                                            +----------------------------+
                                                    clip pulled on demand, only after a confirmed hit

 =====================================================================================
 Raw video never crosses into the central tier. Only structured records do.
 =====================================================================================
```

### 2.2 Deployment model

One codebase, two roles, selected by configuration:

| Role | Setting | Responsibility |
|---|---|---|
| Edge / regional node | `EDGE_MODE=true`, `EDGE_CENTRAL_URL` set | Decode, detect, recognise, match, spool |
| Central server | default | Registry, index, trace, alerting, console, retention |

A district node in Valsad or Dahod keeps detecting through a link outage. Results
queue in a bounded local SQLite spool, default 100,000 rows, and replay in order,
at-least-once, when the uplink returns.

### 2.3 Component responsibilities

| Component | Responsibility |
|---|---|
| Adapter layer | Speaks one departmental dialect each, returns one normalised camera record |
| Camera worker | One thread per camera; TCP streams, sampled decode, presentation-timestamp timing, backoff |
| Plate cascade | Vehicle detect, plate detect on crop, Indian-tuned recognition, consensus voting |
| Face engine | Detection and embedding for enrolled wanted and missing persons |
| Watchlist matcher | Edit-distance tolerant plate matching, face similarity |
| Offline spool | Durable queue, ordered replay on reconnect |
| Access and audit gate | Role check, session check and audit write on every mutation |
| Metadata index | Cameras, sightings, detections, watchlists, alerts, accounts, audit |
| Trace service | Movement reconstruction with spatio-temporal validation |
| Evidence service | Court-format export with hashed snapshots and chain of custody |
| Retention service | Prunes past the window, preserves anything under an open alert |

---

## 3. Integration approach for heterogeneous cameras and VMS

### 3.1 The adapter contract

Every departmental system is reached through one adapter. The rest of the
platform only ever sees a normalised camera record and a stream URL, so
onboarding a new vendor means writing one adapter rather than touching the
registry, the workers or the console.

The normalised record carries identity, stream URLs, coordinates, compass
heading, field of view and nominal ground range, regardless of origin.

### 3.2 Implemented adapters

| Adapter | Covers | Mechanism |
|---|---|---|
| State grid | The Gujarat Police feed | RTSP, HLS and WebRTC, credentials redacted from every log and export |
| ONVIF Profile S | Any conformant IP camera | Network discovery, then probe and onboard. Disabled by default, because a multicast scan is a hostile surprise on a live network |
| Manual RTSP | Any device or recorder channel | Configured by name and URL. The fallback that works when nothing else does |
| File archive | Recorded footage on disk | A directory federated as a second, non-network source |

### 3.3 Camera and protocol coverage

| Camera type | How it is reached |
|---|---|
| IP camera, ONVIF conformant | ONVIF adapter, discovery and probe |
| IP camera, non-conformant | Manual RTSP adapter, vendor URL template |
| Analog camera | Through its DVR or encoder channel, exposed as RTSP per channel |
| Behind a vendor VMS | VMS API or SDK, added as a new adapter against the same contract |
| Archived footage | File archive adapter |

Analog estates are integrated at the recorder, not the camera. The DVR already
digitises and exposes channels; the adapter maps each channel to one registry
entry with its own coordinates.

### 3.4 Ingest hardening

Written against the published integrator guide. The points that break naive
pipelines, all handled:

- **RTSP forced over TCP.** UDP corrupts frames across network address
  translation and presents as a model fault.
- **Timing from presentation timestamps, never arrival.** On connect the gateway
  replays its buffered group of pictures, so the first second arrives faster than
  real time. A tracker timestamping on arrival computes impossible velocities
  after every reconnect.
- **Declared frame rate is unreliable.** Nothing derives from the reported
  capture property.
- **Feeds loop.** The scene cuts hard at the loop point, so background models and
  track identities survive it.
- **Mixed H.264 and H.265, mixed resolutions.** Per-camera properties come from
  the catalogue; a fixed-shape inference batch does not work.
- **Each client receives its own copy of the stream.** Only streams actually
  being processed are opened.

### 3.5 Federating the vehicle records service

Federation is not only about cameras. Vehicle registration and penalty lookups
run through a separate deployable service with its own provider chain, cache,
rate limiting and circuit breaker, because those lookups are billed per call
against third-party vendors and have failure characteristics nothing else in
the platform shares.

The platform delegates to it when a service URL is configured, and answers
in-process when one is not. That keeps two properties at once: a single-node
district install stays one deployable with no extra moving parts, and a
statewide install gets provider failover and a shared cache in front of paid
vendor endpoints. An unreachable service falls back in-process rather than
failing the investigation, and each trace reports which path answered so an
investigator can see it.

---

## 4. Video analytics approach

### 4.1 Number plate recognition, a vehicle-first cascade

Tiled full-frame plate detection measured four to eight seconds per frame and
returned unusable reads. Finding the vehicle first is both faster and higher
recall.

```
  frame --> 1. detect vehicles --> 2. detect plate --> 3. read characters --> 4. consensus
            car / motorcycle       on enlarged crop,   Indian-tuned            several reads
            bus / truck            shape and size      recogniser with         must agree within
                                   gated               a confidence score      a small edit distance
```

Single-frame reads of one physical plate disagree with each other. The prefix and
body stay stable while the last one or two characters drift and the state code
occasionally flips. Multi-frame Levenshtein consensus with Indian-format
positional coercion is what makes the output usable as evidence rather than as a
suggestion. Watchlist matching is correspondingly edit-distance tolerant, so an
imperfect read still raises the alert.

### 4.2 Cross-camera tracking and route reconstruction

A plate query assembles every sighting into a chronological chain and projects it
onto the GIS map. Consecutive sightings are then validated against the haversine
distance between the two cameras and the elapsed time between them. A hop nobody
could physically have driven is flagged inside the route rather than quietly
presented as fact.

This is the difference between a plate search and an evidence trail. The system
states plainly when it does not believe itself.

### 4.3 Person analytics

The brief names wanted and missing persons, which a plate reader cannot answer. A
face engine runs on the same frames, enrolling a subject from a single
photograph. It executes only when somebody is actually enrolled, and is capped so
that heavy matching cannot saturate a node.

### 4.4 Crowd density and anomalies

The detector was already finding people and the vehicle cascade was discarding
them. Counting them therefore costs one extra slice of the score matrix rather
than a second inference pass, and it turns an existing cost into a Model 4
deliverable.

Two anomaly detectors run on that channel, both **relative to each camera's own
rolling median rather than to one statewide number**. This is the design point.
A bus terminal at forty people is ordinary and a rural junction at fifteen is
not, so a fixed threshold would either drown the terminal operator in alerts or
say nothing at the junction.

| Detector | Fires when | Why it is shaped this way |
|---|---|---|
| Crowd surge | The count clears an absolute floor **and** a multiple of that camera's median | The floor alone would alert on every busy camera. The ratio alone would call an empty lane going from one person to three a crowd. Both must hold |
| Loitering | A person track stays inside a small radius past a dwell threshold | Anchored, not averaged. Someone who walks away resets their own anchor rather than slowly dragging a mean along behind them |

Anomalies carry an evidence frame hashed like every other artifact, and they
follow the alert lifecycle: an operator acknowledges, and retention preserves
anything unacknowledged regardless of age. Every figure is reported alongside
the baseline it was measured against, because a headcount without the camera's
normal tells an operator nothing.

### 4.5 Model 4 analytics conformance

| Capability | Status |
|---|---|
| ANPR | Implemented, vehicle-first cascade with consensus |
| Face recognition | Implemented, enrolment from one photograph |
| Vehicle counting and classification | Implemented: car, motorcycle, bus, truck |
| Statewide vehicle tracking and route reconstruction | Implemented, with spatio-temporal validation |
| VAHAN and SARTHI | Connector implemented |
| eGujCop | Connector implemented |
| CCTNS | Connector implemented |
| AFIS / NAFIS | Connector implemented |
| Crowd counting | Implemented, same detector pass as the vehicle log |
| Anomaly detection | Implemented: crowd surge and loitering |

Government connectors run against documented record shapes; live endpoints are
supplied at deployment. Each connector either answers or reports itself
unreachable, and the investigator sees which did which, so one authority being
down never silently loses the answers from the others.

### 4.6 Measured performance

Development box: Ryzen 5 3550H, GTX 1650 4 GB, 6 GB usable RAM. Entry-level
hardware deliberately, because a district node should not need a datacentre card.

| Workload | CPU | CUDA |
|---|---|---|
| Full cascade, median per frame | 1186 ms | 523 ms |
| Full cascade, throughput | 0.84 fps | 1.91 fps |
| Peak video memory | not applicable | 718 MB of 4096 |

| Decode path | Result |
|---|---|
| NVDEC, 1080p, realistic noisy content | ~555 fps aggregate, flat from 8 to 16 streams |
| Software decode, same content | ~435 fps, consuming all 8 CPU threads |
| AMF decode | Unusable, falls back to `d3d11va` |

Accelerator availability is confirmed by executing a real workload on the device,
because the runtime advertises its provider whenever it was compiled with one,
whether or not the libraries actually load.

---

## 5. Geographically dispersed deployment

### 5.1 Why processing sits at the edge

| Path | Sustained backhaul | 30-day storage |
|---|---|---|
| Centralise 80,000 streams at 2 Mbps | 160 Gbps | ~52 PB |
| Centralise structured metadata instead | ~1.5 Mbps aggregate | ~16 GB per day |

The second row is the design. Analysis happens beside the cameras and only the
result travels.

### 5.2 Low-bandwidth and unreliable-link strategy

- **Sampled decode.** Three frames per second are pulled per camera, not the
  stream frame rate.
- **Motion gating.** Inference runs only once a configurable fraction of pixels
  has changed, default 0.4 percent.
- **Analytics slots.** Cameras beyond the node's slot count are onboarded and
  viewable but cycled through analytics rather than run continuously.
- **Durable spool.** Link loss queues results locally and replays them in order
  on reconnect.
- **Backoff with alternate URLs.** A camera that stops responding is retried with
  growing backoff against an alternate stream URL, so one dead feed cannot starve
  the others.
- **Graceful degradation.** Without the recognition models the platform still
  runs as a registry and health monitor. Capability is layered, not
  all-or-nothing.

### 5.3 Video on demand

The only flow that moves video between tiers is an operator requesting a clip
against a confirmed hit. The console asks the edge node, which serves the segment
from the department's own storage.

---

## 6. Scalability to approximately 80,000 cameras

### 6.1 Compute sizing

Measured capacity on the entry-level development box is 12 concurrent analytics
slots with 30 cameras onboarded and cycled.

| Tier | Unit | Cameras per unit | Basis |
|---|---|---|---|
| Edge, entry class | GTX 1650 class, 4 GB | ~30 onboarded, 12 analytics-active | Measured |
| Edge, deployment class | T4 or L4 class, 16 GB | ~150 to 200 | Extrapolation, must be re-benchmarked |
| Central | CPU cluster, no inference | All metadata | Index and API only |

At the deployment-class figure, 80,000 cameras need roughly 400 to 530 regional
nodes. Gujarat has 33 districts and roughly 250 talukas, so this is on the order
of two nodes per taluka.

**This extrapolation is the largest open assumption in the plan and must be
validated by benchmarking on the procured accelerator before any bulk order.**
Capacity settings are configuration rather than code, so re-benchmarking on new
hardware is a settings change, not a rewrite.

### 6.2 Accelerator capacity

- Half precision and a 512-pixel detector input are already the default.
- Peak video memory measured at 718 MB, so a 4 GB card has headroom. An arena
  limit bounds usage on a card also driving a display.
- **Batched inference is implemented.** Camera workers no longer call the
  detector session directly. Each hands a prepared tensor to one collector
  thread, which gathers whatever arrives inside a short window and runs it
  together. Two effects: the accelerator sees one caller instead of thirty
  contending threads, and where the exported model has a dynamic batch
  dimension several frames go through per call.

  Most exports pin batch to one. That case is detected rather than assumed, and
  the collector loops instead of stacking, so the serialisation benefit still
  applies and nothing throws on the first frame of a live deployment. A
  saturated queue, a timeout or a collector that is not running each fall back
  to running detection inline, so a batcher fault costs throughput rather than
  dropping frames.

### 6.3 Network bandwidth planning

| Segment | Load |
|---|---|
| Camera to edge node | Department LAN, unchanged, no new wide-area cost |
| Edge node to centre | Structured records only, kilobits per node under normal load |
| Centre to console | API and alert socket, negligible |
| Clip retrieval | Bursty, on demand, only against a confirmed hit |

### 6.4 Storage tiers

Video is never tiered centrally because it never arrives centrally. Tiering
applies to the metadata estate and to evidence artifacts.

| Tier | Contents | Retention | Medium |
|---|---|---|---|
| Hot | Live sightings, detections, alerts, camera state, sessions | 90 days | Solid state, primary database |
| Warm | Aged sightings and detections, compressed | 12 months | Object storage, queryable on request |
| Cold | Evidence exports and hashed snapshots under legal hold | Per case lifecycle | Write-once archival |
| Department-local | All raw video | Department's own policy, unchanged | Department's own storage |

Retention prunes automatically past the configured window while deliberately
preserving anything attached to an unacknowledged alert, so housekeeping can
never destroy an open evidence chain. Cached third-party records fall under the
same window rather than being exempt because they are a cache.

### 6.5 Horizontal scaling and load balancing

- The API is stateless and authenticates by bearer token, so it scales behind a
  standard load balancer with no session affinity.
- Edge nodes scale by addition. Each owns a disjoint set of cameras.
- The central metadata index is the one vertical component and moves to PostGIS
  with read replicas for query fan-out.
- **Alert fanout scales across instances.** The hub has two modes. Unset, it
  keeps the in-process socket fanout, which is correct and dependency-free for
  the single central instance a district deployment runs. Pointed at a Redis
  URL, events publish to a channel and every instance's subscriber delivers to
  its own sockets, so the central tier can sit behind a load balancer without
  an operator missing an alert raised elsewhere.

  Delivery is loopback: a publisher does not also send locally, because its own
  subscriber receives the message. If the publish fails it sends locally
  anyway, since a degraded fanout beats a dropped alert. A bus that will not
  come up leaves the in-process path in place and records why rather than
  stopping the server from booting.

### 6.6 Monitoring, logging and health checks

Camera health is tracked as online, offline or unknown with last-seen timestamps,
rolled up by department and district, and surfaced on a fleet view alongside
analytics yield and worker state. Device and model state is reported per node.
Every mutating request is written to an append-only audit log.

Two probes answer different questions on purpose. Liveness answers "is the
process up", which is all a load balancer needs. Readiness answers "can this
node actually do its job", which is the question that matters when a district
node is quietly failing: the process is alive, the database is unreachable, and
nothing fires because the liveness probe is green.

Metrics are exposed in Prometheus exposition format, written directly rather
than through a client library. Alongside cameras, workers, frames, detections,
plate reads, open alerts, disk headroom and edge spool depth, the endpoint
reports people currently in frame, open and hourly anomalies by kind, detector
batch counters with mean batch size, and whether the shared alert bus is
connected.

### 6.7 High availability, backup and disaster recovery

| Component | Failure mode | Mitigation | Target |
|---|---|---|---|
| Edge node | Hardware or power loss | Cameras reassigned to a neighbouring node. Department video unaffected | Recovery in hours |
| Uplink | Link down | Durable local spool, ordered replay | No data loss, bounded by spool size |
| Central database | Corruption or loss | Streaming replication to a standby, daily base backup with continuous write-ahead-log archive | Minutes of data, under an hour to restore |
| Central site | Site loss | Warm standby at a second data centre, restored from replicated backups | Under a day |
| Evidence artifacts | Tampering | Cryptographic digest recorded at capture and printed beside every record | Detectable |

---

## 7. Cybersecurity, privacy and accountability

### 7.1 Access control

Three roles, enforced in one middleware over every mutation rather than
per-route, so a router added later is closed by default rather than accidentally
open.

| Role | Can |
|---|---|
| Viewer | Read dashboards, search, export |
| Operator | Plus acknowledge alerts, start and stop analytics, edit the watchlist |
| Administrator | Plus registry changes, onboarding, account administration |

The server refuses a call regardless of what the interface chooses to show.

### 7.2 Credential handling

Passwords are stored only as salted, heavily iterated hashes and are never
recoverable. Camera and vendor credentials are redacted from every log and every
export. Deactivating an account, changing its role or resetting its password ends
every session it holds on the next request, not whenever its token happens to
expire.

### 7.3 Audit

Every state-changing call records the caller, the target and the outcome.
Denials are recorded too, so a failed-permission pattern is visible after the
fact. Failed logins are recorded before the rejection returns. Accounts are
deactivated and never deleted, so past actions stay attributable to a named
officer.

### 7.4 Data protection

Purpose-bound search, a per-subject access log and a recorded case reference for
every trace are the next control set, aligned to the Digital Personal Data
Protection Act. These are listed in section 10.2.

---

## 8. Cost-benefit analysis

### 8.1 Avoided quantities

These follow from the architecture and are the basis of the case. Unit costs are
**indicative planning figures and must be replaced with the department's own rate
contract pricing** before any budgetary submission.

| Avoided item | Quantity avoided | Basis |
|---|---|---|
| Central video storage | ~52 PB at 30-day retention | 80,000 cameras at 2 Mbps |
| Sustained backhaul | 160 Gbps | Same |
| Camera replacement | 80,000 cameras | Federation, not replacement |
| Recorder and VMS replacement | Every departmental recorder and licence | Departments keep their infrastructure |

### 8.2 Cost drivers introduced

| Item | Scale | Note |
|---|---|---|
| Regional inference nodes | ~400 to 530, subject to section 6.1 validation | The dominant capital line |
| Central servers and database | One primary cluster plus a standby site | Modest, carries no video |
| Metadata storage | ~16 GB per day, roughly 6 TB per year statewide | Negligible against 52 PB |
| Integration effort per department | One adapter per distinct VMS platform | One-time, reusable statewide |
| Operations | Node monitoring, model refresh, account administration | Ongoing |

### 8.3 The comparison

The alternative architecture, a single central video management system ingesting
every stream, incurs the 52 PB and 160 Gbps above as permanent recurring cost,
plus a storage refresh cycle. The federated architecture converts that into a
one-time distributed compute purchase and roughly 6 TB per year of metadata.

The saving is not marginal. Metadata is on the order of four orders of magnitude
smaller than the video it describes.

### 8.4 Operational benefit

| Measure | Today | With SENTINEL |
|---|---|---|
| Trace one vehicle across departments | Days. A phone call, a journey and a manual export per department, in office hours | Seconds, one query |
| Coverage planning | Spreadsheet inventory | Map with evidenced blind spots |
| Evidence preparation | Manual screenshots pasted into a report | Reproducible court-format export with hashed images |
| Cross-department query | Not possible | Single query across every federated estate |

The non-monetary benefit is the one that matters operationally. An investigation
that currently depends on knowing which department holds which recording becomes
a registration number typed into one field.

---

## 9. Technical information required from each department

Integration feasibility depends on the following being supplied per department.
This is the concrete ask that follows adoption.

### 9.1 Per department

| Item | Why it is needed |
|---|---|
| Technical single point of contact | Every item below resolves through this person |
| Camera inventory, as a spreadsheet or export | Seeds the registry via bulk import |
| Recorder and VMS inventory: vendor, model, firmware, licence tier | Determines whether an existing adapter applies or a new one is needed |
| API or SDK availability and documentation for the VMS | Decides adapter feasibility versus falling back to RTSP |
| ONVIF conformance profile per camera model | Decides whether discovery can be automated |
| Retention policy and storage location per estate | Sets what clip retrieval can promise |
| Network topology: addressing, virtual LANs, address translation and firewall posture | Determines reachability from the regional node |
| Available bandwidth at each site | Sizes node placement |
| Credential provisioning policy and a service account | Required for any stream access |

### 9.2 Per camera

| Field | Notes |
|---|---|
| Stable identifier | Must survive recorder replacement |
| Make, model, resolution, codec, frame rate | Drives per-camera decode properties |
| Latitude and longitude | Mandatory for GIS and route validation |
| Compass heading, field of view, nominal ground range | Required for coverage and blind-spot analysis |
| Mounting height and tilt | Improves ground-contact projection accuracy |
| Stream URL or recorder channel mapping | Analog channels map one to one with registry entries |
| Owning department and district | Drives role scoping and rollups |

Latitude, longitude and heading are the fields most often missing from existing
inventories, and they are the ones that gate coverage analysis. Where they are
absent, bulk import accepts the camera and flags it as unlocated so it can be
surveyed rather than silently dropped.

---

## 10. Scalability roadmap and phased rollout

### 10.1 Phased statewide rollout

| Phase | Scope | Outcome |
|---|---|---|
| 0, pilot | One district, one department, existing hardware | Validates adapters and node sizing against a real estate |
| 1, registry statewide | Model 1 only, all departments, no analytics | Immediate value: a statewide inventory, health view and coverage map. No accelerators required |
| 2, federation | Adapters for the two or three dominant departmental VMS platforms | Unified viewing across estates |
| 3, priority corridors | Analytics nodes on highways, borders and high-crime junctions | Plate recognition and watchlist alerting where it pays first |
| 4, statewide analytics | Remaining talukas | Full coverage |

Phase 1 is deliberately first and deliberately cheap. It is the compulsory Model
1 deliverable, it needs no accelerators, and it produces the camera inventory
that every later phase depends on.

### 10.2 Engineering roadmap

| Item | Why |
|---|---|
| Re-benchmark on the procured accelerator | Converts the section 6.1 sizing extrapolation into a measurement. The batcher is in place; what remains is running it on deployment hardware |
| Case files linked to an FIR number | Sightings, alerts and exports attached to a case rather than left floating |
| Purpose-bound search with a per-subject access log | Digital Personal Data Protection Act alignment |
| Jurisdiction scoping | Accounts scoped to a district or range, cross-jurisdiction access requested explicitly and recorded |
| Operator review queue | Officers confirm or correct plate reads. Corrections become ground truth and accuracy becomes a measured figure |

---

## 11. Current implementation status

| Measure | Value |
|---|---|
| API endpoints | 76 |
| Console screens | 16 |
| Federation adapters | 4 |
| Persisted data models | 10 |
| Lines of application code | 14,909 |

Test coverage includes plate matching, role enforcement, immediate session
revocation, the offline spool, evidence export, retention behaviour and the API
end to end.

### 11.1 Model 1 requirement conformance

| Required feature | Status |
|---|---|
| Bulk, manual and API-based camera onboarding | Implemented, with CSV bulk import |
| Interactive GIS map with layered filters | Implemented |
| Camera health monitoring | Implemented, with department and district rollups |
| Gap-analysis reports | Implemented, with CSV export |
| Role-based search and audit trails | Implemented |

### 11.2 Model 3 requirement conformance

| Required property | Status |
|---|---|
| Middleware layer rather than direct integration | Implemented |
| Multiple departmental platforms via API, SDK or metadata exchange | Implemented, 4 adapters |
| Departments retain their own infrastructure | By design. Nothing in Band 1 is altered |
| Centralised event correlation | Implemented, trace and watchlist matching |

### 11.3 Model 4 analytics conformance

Model 4 is not the model this entry claims. These are listed because hybrid
submissions are explicitly permitted, and because the capabilities are built
rather than planned.

| Model 4 analytics requirement | Status |
|---|---|
| ANPR | Implemented |
| Face recognition | Implemented |
| Crowd counting | Implemented |
| Vehicle counting and classification | Implemented |
| Anomaly detection | Implemented, crowd surge and loitering |
| Statewide vehicle tracking and route reconstruction | Implemented, with spatio-temporal validation |
| Integration readiness: VAHAN, SARTHI, eGujCop, AFIS, NAFIS | Connectors implemented against documented record shapes |

What Model 4 additionally requires and this architecture deliberately does not
provide is central recording, storage and playback of every stream. That is the
52 PB and 160 Gbps in section 5.1, and declining it is the entry's central
design decision rather than an omission.
