"""Address -> (lat, lon, state_code) geocoding via OpenStreetMap Nominatim.

Online with a local cache. If the network is unavailable or offline mode is on,
geocoding fails gracefully and callers fall back to the UNKNOWN region.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

from .cache import JsonCache

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "PowerGuard/0.1 (outage-risk-demo)"
_cache = JsonCache("geocode")  # geocoding results are stable; no TTL


@dataclass
class GeoResult:
    lat: float
    lon: float
    state_code: Optional[str]
    display_name: str


def geocode(address: str, *, offline: bool = False, timeout: float = 8.0) -> Optional[GeoResult]:
    """Geocode an address. Returns None if it can't be resolved."""
    key = address.strip().lower()
    cached = _cache.get(key)
    if cached:
        return GeoResult(**cached)

    if offline:
        return None

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": address,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
                "countrycodes": "us",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError):
        return None

    if not results:
        return None

    top = results[0]
    details = top.get("address", {}) or {}
    result = GeoResult(
        lat=float(top["lat"]),
        lon=float(top["lon"]),
        state_code=_state_code(details.get("state")),
        display_name=top.get("display_name", address),
    )
    _cache.set(key, result.__dict__)
    return result


# Minimal state-name -> code map for resolving Nominatim's state field.
_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def _state_code(state_name: Optional[str]) -> Optional[str]:
    if not state_name:
        return None
    return _STATES.get(state_name.strip().lower())
