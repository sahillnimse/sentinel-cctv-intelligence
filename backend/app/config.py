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
    # Mutating /api calls always require a token. Reads are open by default so
    # the sandbox dashboards work without a login; set true to lock them too.
    auth_enforce_reads: bool = False
    sample_interval_ms: int = 400
    min_plate_confidence: float = 0.5
    # boot: how many cameras auto-start, and the delay between each starting
    # (stagger prevents a memory spike from 30 HEVC decoders at once)
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

    # Agentic copilot via OpenRouter (OpenAI-compatible). Set the key in .env
    # to activate; the UI shows a setup hint until then.
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    class Config:
        env_file = BASE_DIR / ".env"
        extra = "ignore"


settings = Settings()
settings.snapshot_dir.mkdir(parents=True, exist_ok=True)

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
