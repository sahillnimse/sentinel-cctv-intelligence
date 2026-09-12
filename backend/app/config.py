import os
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/

# Per the Sentinel grid integrator guide: RTSP must run over TCP (UDP corrupts
# frames across NAT). Applies to every OpenCV FFmpeg capture in the process.
# stimeout = socket timeout in microseconds so dead streams fail fast.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;10000000")


class Settings(BaseSettings):
    database_url: str = f"sqlite:///{BASE_DIR / 'sentinel.db'}"
    jwt_secret: str = "dev-secret-change-me"
    admin_username: str = "admin"
    admin_password: str = "admin123"
    operator_username: str = "operator"
    operator_password: str = "operator123"
    viewer_username: str = "viewer"
    viewer_password: str = "viewer123"
    token_ttl_hours: int = 12
    # Mutating /api calls always require a token. Reads also require a token
    # unless this is set false (closed-network sandbox only).
    auth_enforce_reads: bool = True
    # Mark the session cookie Secure so browsers only send it over HTTPS. Must
    # be false for plain-HTTP local development, where a Secure cookie is never
    # sent at all and every request looks unauthenticated. Turn it on for any
    # deployment that terminates TLS.
    cookie_secure: bool = False
    sample_interval_ms: int = 400
    min_plate_confidence: float = 0.5
    # Where the models run: auto | cuda | cpu.
    #   auto  use the GPU when a real probe succeeds, else CPU
    #   cuda  require the GPU, and log an error rather than degrade quietly
    #   cpu   never touch the GPU
    # Needs onnxruntime-gpu; the plain onnxruntime wheel has no CUDA provider
    # and auto will correctly land on CPU.
    inference_device: str = "auto"
    cuda_device_id: int = 0
    # Cap the CUDA arena. Every camera worker shares one session, so this is a
    # process-wide budget. 0 means no cap; set it on a small card (a 4 GB board
    # driving a desktop has roughly 3.5 GB to give).
    cuda_mem_limit_mb: int = 0
    # boot: how many cameras auto-start, and the delay between each starting
    # (stagger prevents a memory spike from 30 HEVC decoders at once).
    #   negative -> every camera that has a stream URL
    #   0        -> autostart disabled, nothing comes up until an operator
    #               presses Start All (this is what the test suite uses)
    #   positive -> cap, for constrained machines
    # 0 meaning "none" is easy to read as "no limit", so _autostart_workers
    # logs which of the three it took at boot.
    autostart_max_cameras: int = 30
    autostart_stagger_ms: int = 800
    # sandbox simulation: generate live detections when the grid is unreachable
    demo_simulate: bool = False
    # DB retention: prune detections/sightings older than this so a long-running
    # session (or looping clips) can't grow the DB unbounded. 0 disables.
    detection_retention_min: int = 240
    go2rtc_url: str = "http://localhost:1984"

    # Edge tier. Off by default: the same codebase runs as the central server
    # or as a district node depending on these.
    edge_mode: bool = False
    edge_node_id: str = "edge-01"
    edge_central_url: str = ""
    edge_token: str = ""
    edge_timeout_s: float = 10.0
    edge_spool_path: Path = BASE_DIR / "spool" / "edge.db"
    edge_spool_max_rows: int = 100_000

    # --- federation adapters ---
    # ONVIF WS-Discovery scans the local network for cameras. Off by default:
    # multicast on an unknown network is a surprise nobody asked for.
    onvif_discovery_enabled: bool = False
    onvif_discovery_timeout_s: float = 4.0
    onvif_default_department: str = "Police"
    # Manually configured RTSP kit: comma-separated "name=url" pairs.
    rtsp_sources: str = ""
    rtsp_default_department: str = "Police"
    # A directory of video files federated as a second, non-network system.
    local_media_dir: str = ""
    local_media_department: str = "Archive"
    snapshot_dir: Path = BASE_DIR / "snapshots"

    # Sentinel camera grid (government-provided mock feeds)
    grid_catalog_url: str = "https://cctv.corp8.cloud/cameras.json"
    grid_rtsp_base: str = "rtsp://103.250.160.189:8554/stream"
    grid_hls_base: str = "https://cctv.corp8.cloud"
    grid_whep_base: str = "http://103.250.160.189:8889/stream"
    # HLS/catalogue sit behind the access password. After logging in at
    # cctv.corp8.cloud in a browser, paste the session cookie here to let
    # sync-grid read the live catalogue; RTSP needs no auth.
    grid_access_cookie: str = ""
    # Grid media auth (per the integrator guide): RTSP & WHEP authenticate
    # with your registered email + access password embedded in the URL
    # (rtsp://email:password@host...). Only approved-list emails connect.
    # HLS goes over the CDN host with the same access password.
    grid_email: str = ""
    grid_password: str = ""

    # Agentic copilot via OpenRouter (OpenAI-compatible). Set the key in .env
    # to activate; the UI shows a setup hint until then.
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # --- vehicle RTO / challan trace (RapidAPI) ---------------------------
    # Keys never leave the server: the frontend calls /api/vehicle/* and the
    # backend fans out to RapidAPI. Quotes are stripped so both
    # RAPIDAPI_KEY=abc and RAPIDAPI_KEY="abc" work.
    rapidapi_key: str = ""
    rapidapi_host: str = ""
    rapidapi_challan_host: str = ""
    rapidapi_rc_path: str = "/getVehicleInfo"
    rapidapi_challan_path: str = "/getChallans"
    rapidapi_timeout_s: float = 10.0
    # How long a stored vehicle trace answers from cache before going live
    # again. Refresh (?refresh=true) bypasses it on demand.
    vehicle_trace_cache_ttl_s: int = 3600

    # --- vehicle microservice federation ---
    # When set, challan lookups are delegated to the standalone vehicle
    # service (vehicle-service/, its own providers, cache and circuit breaker)
    # instead of the in-process vendor call. Empty keeps everything in-process,
    # so the platform still runs as a single deployable.
    vehicle_service_url: str = ""
    vehicle_service_timeout_s: float = 8.0

    # --- crowd analytics ---
    # People are already in the detector's output; the cascade simply filtered
    # them out. Counting them costs one extra class slice, not another pass.
    crowd_counting_enabled: bool = True
    # Persist a count at most this often per camera, so a busy junction does
    # not write a row per sampled frame.
    crowd_sample_seconds: float = 5.0

    # --- anomaly detection ---
    anomaly_enabled: bool = True
    # A surge fires when the count clears this floor AND this multiple of the
    # camera's own rolling median. The floor stops an empty lane going from one
    # person to three and calling it a crowd.
    crowd_surge_min_people: int = 12
    crowd_surge_ratio: float = 2.5
    # Dwell time before a stationary person is called loitering, and the radius
    # (fraction of frame width) they must stay inside to count as stationary.
    loiter_seconds: float = 120.0
    loiter_radius_frac: float = 0.06
    # Suppress repeat anomalies of the same kind on one camera.
    anomaly_dedup_seconds: float = 180.0

    # --- batched inference ---
    # Camera workers hand frames to one shared batcher rather than each calling
    # the session directly. Serialises accelerator access and, when the model
    # has a dynamic batch dimension, runs several frames per call.
    inference_batching_enabled: bool = True
    inference_batch_size: int = 4
    # How long the batcher waits to fill a batch before running what it has.
    inference_batch_wait_ms: int = 25

    # --- alert bus ---
    # Empty keeps the in-process socket fanout, which is correct for a single
    # central instance. Set a Redis URL to fan alerts out across instances so
    # the central tier can run behind a load balancer.
    alert_bus_url: str = ""
    alert_bus_channel: str = "sentinel.alerts"

    class Config:
        env_file = BASE_DIR / ".env"
        extra = "ignore"


settings = Settings()


def _anchor_sqlite_path(url: str) -> str:
    """Resolve a relative SQLite file path against backend/ rather than the
    process working directory.

    DATABASE_URL=sqlite:///./sentinel.db means a different file depending on
    where uvicorn was launched from. Running it from the repository root
    instead of backend/ creates a second, empty database, and the console then
    comes up with an empty camera registry and a dark live wall for no visible
    reason. The path in the URL is meant to name the deployment's database, not
    the operator's current directory.

    Absolute paths, :memory:, and every non-SQLite driver are left untouched.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    path = url[len(prefix):]
    if not path or path.startswith(":memory:"):
        return url
    if Path(path).is_absolute():
        return url
    return prefix + (BASE_DIR / path).resolve().as_posix()


settings.database_url = _anchor_sqlite_path(settings.database_url)
settings.snapshot_dir.mkdir(parents=True, exist_ok=True)

_DEFAULT_PASSWORDS = {"admin123", "operator123", "viewer123"}
if {settings.admin_password, settings.operator_password, settings.viewer_password} & _DEFAULT_PASSWORDS:
    import warnings as _pw_warnings
    _pw_warnings.warn(
        "Default role passwords are still in use. Change ADMIN_PASSWORD / "
        "OPERATOR_PASSWORD / VIEWER_PASSWORD before any networked deployment.",
        RuntimeWarning, stacklevel=2,
    )

# HS256 wants at least 32 bytes. A short or left-at-default secret makes every
# token forgeable, so replace it with a random one and say so loudly. Tokens
# then don't survive a restart, which is the correct trade for a deployment
# that hasn't set its own secret.
_WEAK_SECRETS = {"dev-secret-change-me", "change-me-in-prod", "secret", ""}
if settings.jwt_secret in _WEAK_SECRETS or len(settings.jwt_secret) < 32:
    import secrets as _secrets
    import warnings as _warnings

    _warnings.warn(
        "JWT_SECRET is weak or unset. Generated an ephemeral one for this "
        "process; sessions will not survive a restart and multiple workers "
        "will not share sessions. Set a 32+ character JWT_SECRET in .env "
        "before deploying.",
        RuntimeWarning, stacklevel=2,
    )
    settings.jwt_secret = _secrets.token_urlsafe(48)
