"""Tiny JSON file cache for geocoding and weather lookups.

Keeps repeated lookups fast, avoids hammering free APIs, and lets recently
fetched data survive a brief loss of connectivity.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_LOCK = threading.Lock()


class JsonCache:
    def __init__(self, name: str, ttl_seconds: Optional[float] = None) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        self._path = CACHE_DIR / f"{name}.json"
        self._ttl = ttl_seconds
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _flush(self) -> None:
        try:
            self._path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass  # cache is best-effort; never fail the app over it

    def get(self, key: str) -> Optional[Any]:
        with _LOCK:
            entry = self._data.get(key)
            if entry is None:
                return None
            if self._ttl is not None and (time.time() - entry.get("ts", 0)) > self._ttl:
                return None
            return entry.get("value")

    def set(self, key: str, value: Any) -> None:
        with _LOCK:
            self._data[key] = {"ts": time.time(), "value": value}
            self._flush()
