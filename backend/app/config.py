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
