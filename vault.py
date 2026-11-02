"""Atomic, versioned file storage for the server folder."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

KEEP_VERSIONS = 20
STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
VERSION_PATTERN = re.compile(r"\d{8}T\d{12}Z\.bak")


def write_atomic(target: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _snapshot(target: Path, relative: str, versions_root: Path) -> None:
    if not target.is_file():
        return
    folder = versions_root / relative
    folder.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime(STAMP_FORMAT) + ".bak"
    shutil.copy2(target, folder / name)
    existing = sorted(p for p in folder.iterdir() if VERSION_PATTERN.fullmatch(p.name))
    for old in existing[:-KEEP_VERSIONS]:
        old.unlink()


def save(target: Path, relative: str, data: bytes, versions_root: Path) -> None:
    _snapshot(target, relative, versions_root)
    write_atomic(target, data)


def delete(target: Path, relative: str, versions_root: Path) -> None:
    _snapshot(target, relative, versions_root)
    target.unlink()


def list_versions(relative: str, versions_root: Path) -> list[dict]:
    folder = versions_root / relative
    if not folder.is_dir():
        return []
    entries = []
    for path in sorted((p for p in folder.iterdir() if VERSION_PATTERN.fullmatch(p.name)), reverse=True):
        created = datetime.strptime(path.name[:-4], STAMP_FORMAT).replace(tzinfo=timezone.utc)
        entries.append({"name": path.name, "size": path.stat().st_size, "created": created.isoformat()})
    return entries


def restore(target: Path, relative: str, name: str, versions_root: Path) -> None:
    if not VERSION_PATTERN.fullmatch(name):
        raise ValueError("Invalid version name.")
    source = versions_root / relative / name
    if not source.is_file():
        raise ValueError("That version no longer exists.")
    save(target, relative, source.read_bytes(), versions_root)


def tree_size(path: Path) -> int:
    total = 0
    if path.is_dir():
        for root, _, files in os.walk(path):
            for name in files:
                full = Path(root) / name
                if not full.is_symlink():
                    total += full.stat().st_size
    return total
