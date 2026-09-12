# Gujarat Police Innovation Challenge 2026 — official brief

Scraped from the FAQ at https://sentinel.gujarat.gov.in/faqs on 12 September 2026.
The `/problems` page was returning a database error, so this is sourced from the
50-question FAQ, which restates the problem statement. Treat the registered
problem-statement document as authoritative if the two ever disagree.

## Integration models

The framework defines **four** reference models, plus the option of a hybrid or
fully customised architecture.

**Model 1 is compulsory for all submissions and must be combined with one or
more of the other models.** It is metadata-only and cannot stand alone.

| Model | Name | Core idea |
|---|---|---|
| 1 | Centralised CCTV Registry & GIS Foundation | Camera metadata registry and GIS mapping. No central streaming or recording. |
| 2 | Unified Viewing and Selective Analytics | Connects **directly** to each departmental VMS. No middleware layer. |
| 3 | VMS Federation and Middleware Layer | Middleware sits between the platform and departmental VMS platforms. |
| 4 | Central VMS and AI Platform | One consolidated central VMS for monitoring, recording, storage and statewide AI analytics. |

### Model 1 — compulsory
Registry and GIS mapping platform for camera metadata: location, department,
type, ownership, connectivity, storage. Provides a unified inventory and
visibility layer for planning and gap analysis.

Required features: bulk, manual and API-based camera onboarding; interactive GIS
map with layered filters; camera health monitoring; gap-analysis reports;
role-based search and audit trails.

Explicitly **not** centralised live streaming or recording. Must be paired with
another model to deliver feed integration, viewing or analytics.

### Model 2
Aggregates feeds into a single interface by connecting directly to each
departmental CCTV/VMS system over RTSP, ONVIF, vendor SDKs or APIs, without
disturbing existing infrastructure. No intermediate federation layer.

### Model 3
A middleware layer integrating multiple departmental VMS platforms via APIs,
SDKs and metadata exchange. Enables interoperability and centralised event
correlation while departments retain their own infrastructure. The difference
from Model 2 is the middleware: Model 3 does not connect directly to each
departmental system.

### Model 4
Centralised monitoring, recording, storage, playback and advanced AI analytics
at statewide scale.

Infrastructure: scalable storage, high-bandwidth connectivity, centralised
compute, redundancy, cybersecurity controls, large-scale ingestion and real-time
processing.

Analytics: ANPR, face recognition, crowd and vehicle counting, anomaly
detection, statewide vehicle tracking and route reconstruction, plus integration
readiness with VAHAN, SARTHI, eGujCop, AFIS and NAFIS.

### Hybrid and custom
Teams may combine elements from two or more models, or submit a fully
innovative architecture, provided it addresses the functional, interoperability,
security, scalability and analytics criteria.

Suggested stacks per model (React, Node.js/Python, PostgreSQL + PostGIS, Kafka,
Kubernetes, S3-compatible storage) are references only, not requirements.

## Design dimensions every solution must cover

Overall architecture; integration strategy for heterogeneous cameras and VMS;
AI and video analytics approach including ANPR and cross-camera tracking;
cybersecurity, privacy, RBAC and audit controls; deployment architecture across
central, regional and edge; infrastructure sizing; cost-benefit analysis;
department-wise technical requirements; scalability roadmap.

## Live technical test case

After registration, teams get roughly 50 geographically distributed
live-simulated camera feeds from different departments, and must onboard them
onto their platform with centralised monitoring and analytics.

A designated vehicle number is given on the hackathon day. The system must track
that vehicle across camera locations over time.

Expected output: the complete route traversed, a timestamped and location-wise
movement history, and evidence of interoperability, onboarding efficiency,
analytics capability and end-to-end performance.

## Submission requirements

Two documents:

1. **Solution Presentation** (PPT/PDF) — model chosen with justification,
   solution overview, key features.
2. **Technical Proposal / High-Level Design** — architecture diagrams,
   integration approach for IP/analog/multi-vendor/varied protocols, handling of
   geographically dispersed locations covering bandwidth and edge versus
   centralised processing, analytics approach including ANPR and cross-camera
   tracking, scalability approach for ~80,000 cameras, and the department-level
   technical details needed for integration feasibility.

Two demonstration videos:

1. Own-feed demo, 2–3 minute screen recording, showing onboarding, live and
   recorded viewing, and vehicle detection / ANPR.
2. Live demonstration on the government-provided feed showing onboarding,
   viewing, and analytics output for ANPR and vehicle, person, intrusion and
   object detection. Must be accompanied by an output report of detected
   vehicles or plates with timestamps.

**Mock-ups, animations and concept videos are explicitly not accepted.**
Demonstrations must show actual working software.

Delivery: unlisted YouTube link, or Google Drive / OneDrive with viewer access.
Optionally a hosted URL with test credentials and a Git repository link.

## Scalability plan (~80,000 cameras)

Central, regional and edge compute requirements; GPU/accelerator capacity;
network bandwidth planning and low-bandwidth strategies; hot/warm/cold storage
tiers by retention; load balancing, horizontal scaling, monitoring, logging and
health checks; high availability, backup and disaster recovery; a phased
statewide rollout plan.

## Evaluation areas

1. Successful test case — onboarding plus analytics on the government feed
2. Solution presentation — clarity, model justification
3. Solution architecture — technical soundness, HLD quality
4. Working platform — maturity of the demonstrated software
5. Video analytics output — quality of ANPR, detection and reports
6. Scalability and PoC readiness at ~80,000 cameras
7. Submission completeness

Bonus consideration is available for innovative hybrid architectures, advanced
cross-camera tracking, additional reliable analytics, edge processing, bandwidth
optimisation, enhanced cybersecurity and auditability, operational dashboards,
automated alerts, health monitoring and integration-ready APIs. Bonus features
do **not** compensate for missing mandatory requirements.

## Dates

| Milestone | Date |
|---|---|
| Registration opened | 01 May 2026 |
| Last date for registration and submission | 15 September 2026 |
| Shortlisting | 18 September 2026 |
| Event | 22–23 September 2026 |
| Results | 24 September 2026 |

Total prize pool ₹51,00,000. Dataset: 30+ cameras across Health, Police, GSRTC,
Panchayat and Municipal, 12 hours of footage per camera plus a live simulation
environment.
