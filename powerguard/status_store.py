"""Persisted 'last known status per address' store for change detection.

Notifications should only fire when something actually changes between runs, so
we remember the previous risk band, score, recovery estimate, and outage flag
for each address (keyed by a normalized address string).
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

STORE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "status_store.json"
_LOCK = threading.Lock()


@dataclass
class StatusSnapshot:
    risk_band: str
    risk_score: float
    estimated_recovery_hours: float
    outage_reported: bool


def _key(address: str) -> str:
    return address.strip().lower()


class StatusStore:
    def __init__(self, path: Path = STORE_PATH) -> None:
        self._path = path
        self._path.parent.mkdir(exist_ok=True)
        self._data: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _flush(self) -> None:
        try:
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def get(self, address: str) -> Optional[StatusSnapshot]:
        with _LOCK:
            raw = self._data.get(_key(address))
            return StatusSnapshot(**raw) if raw else None

    def set(self, address: str, snapshot: StatusSnapshot) -> None:
        with _LOCK:
            self._data[_key(address)] = asdict(snapshot)
            self._flush()
