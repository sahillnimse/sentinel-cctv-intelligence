"""Safe paths under the snapshot directory."""

from pathlib import Path

from ..config import settings


def snapshot_path(filename: str | None) -> Path | None:
    """Resolve a snapshot filename to a file inside snapshot_dir.

    Returns None when the name is empty, missing, or would escape the
    directory (``..``, absolute paths).
    """
    if not filename:
        return None
    name = str(filename).replace("\\", "/").lstrip("/")
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return None
    root = settings.snapshot_dir.resolve()
    path = (settings.snapshot_dir / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None
