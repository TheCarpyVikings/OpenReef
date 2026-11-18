"""Confinement rules shared by OpenReef media readers and writers."""

from __future__ import annotations

from pathlib import Path
import re

_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".mp4"}


def safe_media_id(value: object) -> bool:
    """Accept existing slug IDs without permitting path separators or dot segments."""
    return isinstance(value, str) and bool(_COMPONENT.fullmatch(value))


def capture_path(root: Path, relative: str = "") -> Path:
    """Return a confined path, refusing symlinks anywhere below the managed root.

    The HA configuration directory is trusted. Its managed media child and every
    descendant must be real directories/files, never links to another HA file.
    Call again immediately before filesystem operations on a previously built path.
    """
    if not isinstance(relative, str) or len(relative) > 512:
        raise ValueError("Invalid media path")
    parts = relative.split("/") if relative else []
    if any(not safe_media_id(part) for part in parts):
        raise ValueError("Invalid media path")
    candidate = root
    if candidate.is_symlink():
        raise ValueError("Media symlinks are not permitted")
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError("Media symlinks are not permitted")
    try:
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError) as err:
        raise ValueError("Media path is outside the capture directory") from err
    return candidate


def capture_relative(root: Path, path: Path) -> str:
    """Validate a path constructed internally before using it for I/O."""
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as err:
        raise ValueError("Media path is outside the capture directory") from err
    capture_path(root, relative)
    return relative


def media_file_path(root: Path, relative: str) -> Path:
    """Restrict served/signed content to media in OpenReef's existing layouts."""
    path = capture_path(root, relative)
    parts = relative.split("/")
    if path.suffix.lower() not in _MEDIA_SUFFIXES or not (
        len(parts) == 1
        or (len(parts) == 2 and parts[0] == "corals")
        or (len(parts) == 3 and parts[0] in {"timelapse", "feeds"})
    ):
        raise ValueError("Not an OpenReef media file")
    return path
