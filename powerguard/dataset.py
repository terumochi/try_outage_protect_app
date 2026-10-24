"""Loader for the bundled, fully-offline regional dataset.

The dataset provides the static inputs to the heuristic model: per-region risk,
grid reliability, historical outage frequency, baseline recovery hours, and the
peak storm-season month (used for the offline weather fallback).
"""
from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REGIONS_CSV = DATA_DIR / "regions.csv"


@dataclass(frozen=True)
class Region:
    """Static, offline risk attributes for a geographic region (US state)."""

    state_code: str
    state_name: str
    regional_risk: float          # 0..1 baseline environmental/exposure risk
    grid_reliability: float       # 0..1 higher = more reliable grid
    annual_outage_freq: float     # expected outages per year
    avg_recovery_hours: float     # baseline recovery time in hours
    storm_season_peak_month: int  # 1..12, month of peak storm activity


@functools.lru_cache(maxsize=1)
def load_regions() -> Dict[str, Region]:
    """Load and cache the region table keyed by uppercase state code."""
    regions: Dict[str, Region] = {}
    with REGIONS_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            region = Region(
                state_code=row["state_code"].strip().upper(),
                state_name=row["state_name"].strip(),
                regional_risk=float(row["regional_risk"]),
                grid_reliability=float(row["grid_reliability"]),
                annual_outage_freq=float(row["annual_outage_freq"]),
                avg_recovery_hours=float(row["avg_recovery_hours"]),
                storm_season_peak_month=int(row["storm_season_peak_month"]),
            )
            regions[region.state_code] = region
    return regions


def get_region(state_code: Optional[str]) -> Region:
    """Return the Region for a state code, falling back to UNKNOWN."""
    regions = load_regions()
    if state_code:
        region = regions.get(state_code.strip().upper())
        if region:
            return region
    return regions["UNKNOWN"]
