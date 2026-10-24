"""Orchestration: address -> geocode -> weather -> offline model -> result.

This is the single entry point used by both the manual and CSV input modes in
the Streamlit UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import geocode as geo
from . import weather as wx
from .dataset import Region, get_region
from .model import OutageModel, Prediction, RegionInput, WeatherInput

_model = OutageModel()


@dataclass
class AssessmentInput:
    name: str
    address: str
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class Assessment:
    name: str
    address: str
    resolved: bool
    lat: Optional[float]
    lon: Optional[float]
    region_name: str
    weather: WeatherInput
    prediction: Prediction
    error: Optional[str] = None


def assess(item: AssessmentInput, *, offline: bool = False) -> Assessment:
    """Run the full pipeline for one address."""
    lat, lon, state_code, resolved, error = item.lat, item.lon, None, False, None

    if lat is not None and lon is not None:
        resolved = True  # coordinates supplied directly
    else:
        result = geo.geocode(item.address, offline=offline)
        if result is not None:
            lat, lon, state_code = result.lat, result.lon, result.state_code
            resolved = True
        else:
            error = (
                "Could not geocode address (offline mode)."
                if offline
                else "Could not geocode address; using generic regional baseline."
            )

    region: Region = get_region(state_code)

    if lat is not None and lon is not None:
        weather = wx.get_weather(lat, lon, region, offline=offline)
    else:
        # No coordinates at all -> pure offline seasonal fallback.
        weather = wx.get_weather(0.0, 0.0, region, offline=True)

    prediction: Prediction = _model.predict(weather, RegionInput.from_region(region))

    return Assessment(
        name=item.name or item.address,
        address=item.address,
        resolved=resolved,
        lat=lat,
        lon=lon,
        region_name=region.state_name,
        weather=weather,
        prediction=prediction,
        error=error,
    )
