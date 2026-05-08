"""Atomic JSON storage with file locking and one-step backup (PRD §6.6)."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from filelock import FileLock


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOCK_PATH = str(DATA_DIR / ".lock")


def _atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        # H-6: ensure data hits disk before atomic rename
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # Some filesystems (e.g. certain network mounts) reject fsync.
            pass
    os.replace(tmp, path)


def load_json(path: Path, default: Any) -> Any:
    """Load JSON file. On corruption, restore from .bak; if both fail, return default.

    H-5: When a .bak file successfully decodes, immediately repair the live file
    (move corrupt copy aside as ``.corrupt-<timestamp>``, promote backup to live)
    so that the next write does not overwrite a healthy backup with garbage.
    """
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.exists():
            try:
                with bak.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                # Quarantine the corrupt original, then promote .bak to live.
                ts = time.strftime("%Y%m%d-%H%M%S")
                corrupt = path.with_suffix(path.suffix + f".corrupt-{ts}")
                try:
                    os.replace(path, corrupt)
                    shutil.copyfile(bak, path)
                except OSError:
                    # Best-effort recovery: even if rename fails, return the
                    # successfully decoded backup data so callers can proceed.
                    pass
                return data
        return default


def save_json(path: Path, obj: Any, *, lock: bool = True) -> None:
    """Backup current file, then atomically replace it.

    Pass ``lock=False`` when the caller already holds the global lock
    (avoids re-entrant FileLock timeouts).
    """
    def _do() -> None:
        if path.exists():
            bak = path.with_suffix(path.suffix + ".bak")
            shutil.copyfile(path, bak)
        _atomic_write_json(path, obj)

    if lock:
        with FileLock(LOCK_PATH, timeout=10):
            _do()
    else:
        _do()


def with_lock(timeout: float = 10):
    """Context-manager wrapper for read-modify-write sequences."""
    return FileLock(LOCK_PATH, timeout=timeout)
