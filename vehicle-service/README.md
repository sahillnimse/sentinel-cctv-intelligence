# Vehicle RC / E-Challan Microservice (FastAPI)

Production-ready service to extract, cache and serve Indian RC challan records.

## Run (local, mock providers — no billing)

```bash
cd vehicle-service
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\uvicorn app.main:app --reload --port 8001
```

Docs: http://localhost:8001/docs

## Endpoints

- `GET /api/v1/vehicle/{reg}/fines?force_refresh=true&chassis_number=XXXXX&engine_number=XXXXX`
- `POST /api/v1/vehicle/batch-fines` → `{job_id}` (202) then `GET /api/v1/vehicle/batch-fines/{job_id}`
- `GET /health` → redis + provider + circuit status

## Notes

- Plates are sanitised (strip spaces/hyphens, uppercase) and validated
  (`MH02AB1234`, `DL01C1234`, `KA05MN1234`, `21BH1234AA`).
- Cache key `vehicle:challan:{PLATE}`, TTL `CACHE_TTL_SECONDS` (default 24h).
- Failover: primary → secondary on timeout/5xx/429. Breaker per provider.
- Rate limits: 60/min fines, 10/min batch (slowapi, per IP).
- Audit: set `DATABASE_URL` (postgres) to persist query history, else log-only.
- Real vendors: set `*_PROVIDER_BASE_URL` + `*_PROVIDER_API_KEY` and `MOCK_PROVIDERS=false`.

## RapidAPI live wiring

`vehicle-service/.env` (git-ignored) now mirrors `backend/.env`:

```ini
RAPIDAPI_KEY=<your key>
RAPIDAPI_HOST=in-rto-vehicle-information-india.p.rapidapi.com
RAPIDAPI_BASE_URL=https://in-rto-vehicle-information-india.p.rapidapi.com
RAPIDAPI_PATH=/getVehicleInfo
MOCK_PROVIDERS=false
```

Primary uses `POST {BASE}{PATH}` with `x-rapidapi-key` / `x-rapidapi-host`
and body `{"vehicle_no": "...", "consent": "Y", ...}` (`app/providers/primary_provider.py:46`).
If your dashboard shows a different path/method, set `RAPIDAPI_PATH` accordingly —
no code change needed. `GET /health` reports `up (rapidapi configured)` without
burning quota.
