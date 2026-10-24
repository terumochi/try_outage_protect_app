"""Live weather via Open-Meteo, with a local cache and offline fallback.

Open-Meteo is free and needs no API key. When the network is unavailable (or
offline mode is on), `get_weather` returns a seasonal/historical estimate built
from the bundled region data, flagged with `is_fallback=True` so downstream
output can be marked "degraded".
"""
from __future__ import annotations

import math
from datetime import datetime

import requests

from .cache import JsonCache
from .dataset import Region
from .model import WeatherInput

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# Weather changes; cache for 30 minutes.
_cache = JsonCache("weather", ttl_seconds=30 * 60)

# Open-Meteo WMO weather codes that indicate thunderstorms.
_THUNDER_CODES = {95, 96, 99}


def get_weather(
    lat: float,
    lon: float,
    region: Region,
    *,
    offline: bool = False,
    timeout: float = 8.0,
) -> WeatherInput:
    """Return current weather for a coordinate, or a seasonal fallback."""
    key = f"{round(lat, 2)},{round(lon, 2)}"
    cached = _cache.get(key)
    if cached:
        return WeatherInput(**cached)

    if not offline:
        live = _fetch_live(lat, lon, timeout)
        if live is not None:
            _cache.set(key, live.__dict__)
            return live

    # Fallback: seasonal estimate from region data.
    return _seasonal_fallback(region)


def _fetch_live(lat: float, lon: float, timeout: float) -> WeatherInput | None:
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,precipitation,weather_code,"
                    "wind_speed_10m,wind_gusts_10m,snowfall"
                ),
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
                "timezone": "auto",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        cur = resp.json().get("current", {})
    except (requests.RequestException, ValueError, KeyError):
        return None

    if not cur:
        return None

    code = int(cur.get("weather_code", 0) or 0)
    return WeatherInput(
        wind_speed_kmh=float(cur.get("wind_speed_10m", 0) or 0),
        wind_gust_kmh=float(cur.get("wind_gusts_10m", 0) or 0),
        precip_mm=float(cur.get("precipitation", 0) or 0),
        temperature_c=float(cur.get("temperature_2m", 15) or 15),
        snowfall_cm=float(cur.get("snowfall", 0) or 0),
        thunderstorm=code in _THUNDER_CODES,
        is_fallback=False,
    )


def _seasonal_fallback(region: Region) -> WeatherInput:
    """Build a plausible weather estimate from bundled seasonal data.

    Uses proximity to the region's storm-season peak month to scale hazard, so
    the model still produces sensible (if coarse) results fully offline.
    """
    month = datetime.now().month
    peak = region.storm_season_peak_month
    # Circular distance between current month and storm peak (0..6).
    dist = min((month - peak) % 12, (peak - month) % 12)
    season_factor = 1.0 - (dist / 6.0)  # 1.0 at peak, ~0 opposite the year

    # Scale baseline hazard by regional risk and season.
    intensity = region.regional_risk * season_factor
    return WeatherInput(
        wind_speed_kmh=round(15 + 45 * intensity, 1),
        wind_gust_kmh=round(25 + 70 * intensity, 1),
        precip_mm=round(2 + 20 * intensity, 1),
        temperature_c=round(15 - 10 * math.cos((month - 1) / 12 * 2 * math.pi), 1),
        snowfall_cm=round(8 * intensity, 1) if month in (12, 1, 2) else 0.0,
        thunderstorm=intensity > 0.5,
        is_fallback=True,
    )
