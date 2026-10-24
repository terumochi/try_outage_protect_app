"""The offline heuristic outage-risk model.

This module is pure Python and has **no network dependencies**. It takes
already-gathered inputs (live or fallback weather + bundled regional data) and
deterministically produces an outage-risk score and an estimated recovery time.

Keeping the model offline and deterministic makes it easy to test, audit, and
reason about: the same inputs always yield the same output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .dataset import Region


@dataclass
class WeatherInput:
    """Weather inputs to the model. Units: metric."""

    wind_speed_kmh: float = 0.0        # sustained wind
    wind_gust_kmh: float = 0.0         # peak gust
    precip_mm: float = 0.0             # precipitation in the window
    temperature_c: float = 15.0
    snowfall_cm: float = 0.0
    thunderstorm: bool = False
    is_fallback: bool = False          # True if from offline seasonal estimate


@dataclass
class RegionInput:
    """Subset of bundled region data the model consumes."""

    regional_risk: float
    grid_reliability: float
    annual_outage_freq: float
    avg_recovery_hours: float

    @classmethod
    def from_region(cls, region: Region) -> "RegionInput":
        return cls(
            regional_risk=region.regional_risk,
            grid_reliability=region.grid_reliability,
            annual_outage_freq=region.annual_outage_freq,
            avg_recovery_hours=region.avg_recovery_hours,
        )


@dataclass
class Prediction:
    """Model output."""

    risk_score: float                      # 0..100
    risk_band: str                         # Low / Moderate / High / Severe
    estimated_recovery_hours: float
    contributions: Dict[str, float] = field(default_factory=dict)  # factor -> 0..100 pts
    notes: List[str] = field(default_factory=list)
    degraded: bool = False                 # True if based on fallback weather


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _band(score: float) -> str:
    if score < 25:
        return "Low"
    if score < 50:
        return "Moderate"
    if score < 75:
        return "High"
    return "Severe"


class OutageModel:
    """Transparent, weighted heuristic model.

    The risk score is a weighted blend (0..1, scaled to 0..100) of:
      - weather hazard (wind, gusts, precip, snow, thunderstorm, temperature)
      - regional baseline environmental risk
      - grid fragility (inverse of grid reliability)
      - historical outage frequency

    Recovery time scales the regional baseline by weather severity, grid
    fragility, and the hazard level.
    """

    # Weights for the risk blend (sum to 1.0).
    W_WEATHER = 0.50
    W_REGION = 0.20
    W_GRID = 0.18
    W_HISTORY = 0.12

    def predict(self, weather: WeatherInput, region: RegionInput) -> Prediction:
        weather_hazard = self._weather_hazard(weather)      # 0..1
        grid_fragility = _clamp(1.0 - region.grid_reliability)
        history = _clamp(region.annual_outage_freq / 4.0)   # normalize ~0..1

        risk = (
            self.W_WEATHER * weather_hazard
            + self.W_REGION * region.regional_risk
            + self.W_GRID * grid_fragility
            + self.W_HISTORY * history
        )
        risk = _clamp(risk)
        score = round(risk * 100, 1)

        contributions = {
            "Weather hazard": round(self.W_WEATHER * weather_hazard * 100, 1),
            "Regional baseline": round(self.W_REGION * region.regional_risk * 100, 1),
            "Grid fragility": round(self.W_GRID * grid_fragility * 100, 1),
            "Outage history": round(self.W_HISTORY * history * 100, 1),
        }

        recovery = self._recovery_hours(
            region=region,
            weather_hazard=weather_hazard,
            grid_fragility=grid_fragility,
        )

        notes = self._notes(weather, weather_hazard)
        if weather.is_fallback:
            notes.insert(0, "Weather from offline seasonal fallback (degraded).")

        return Prediction(
            risk_score=score,
            risk_band=_band(score),
            estimated_recovery_hours=round(recovery, 1),
            contributions=contributions,
            notes=notes,
            degraded=weather.is_fallback,
        )

    # --- internal scoring helpers -------------------------------------------

    def _weather_hazard(self, w: WeatherInput) -> float:
        """Blend weather variables into a single 0..1 hazard value."""
        # Each sub-factor is normalized to roughly 0..1 at "severe" levels.
        wind = _clamp(w.wind_speed_kmh / 90.0)          # ~90 km/h sustained = max
        gust = _clamp(w.wind_gust_kmh / 120.0)          # ~120 km/h gust = max
        precip = _clamp(w.precip_mm / 50.0)             # 50 mm = max
        snow = _clamp(w.snowfall_cm / 30.0)             # 30 cm = max
        storm = 1.0 if w.thunderstorm else 0.0

        # Temperature stress: extreme cold or heat strains the grid.
        if w.temperature_c <= 0:
            temp = _clamp((0 - w.temperature_c) / 25.0)     # down to -25C
        elif w.temperature_c >= 32:
            temp = _clamp((w.temperature_c - 32) / 15.0)    # up to 47C
        else:
            temp = 0.0

        # Weighted blend of weather sub-factors (gusts dominate real outages).
        hazard = (
            0.28 * gust
            + 0.22 * wind
            + 0.18 * precip
            + 0.14 * snow
            + 0.10 * storm
            + 0.08 * temp
        )
        return _clamp(hazard)

    def _recovery_hours(
        self, region: RegionInput, weather_hazard: float, grid_fragility: float
    ) -> float:
        """Estimate recovery hours from baseline, scaled by severity."""
        base = region.avg_recovery_hours
        # Worse weather and a more fragile grid lengthen recovery.
        multiplier = 1.0 + (1.6 * weather_hazard) + (0.8 * grid_fragility)
        return max(0.5, base * multiplier)

    def _notes(self, w: WeatherInput, hazard: float) -> List[str]:
        notes: List[str] = []
        if w.wind_gust_kmh >= 70:
            notes.append(f"High wind gusts ({w.wind_gust_kmh:.0f} km/h) — downed-line risk.")
        if w.thunderstorm:
            notes.append("Active thunderstorms increase fault likelihood.")
        if w.snowfall_cm >= 10:
            notes.append(f"Heavy snow ({w.snowfall_cm:.0f} cm) can load lines and trees.")
        if w.precip_mm >= 25:
            notes.append(f"Heavy precipitation ({w.precip_mm:.0f} mm).")
        if w.temperature_c <= -10:
            notes.append(f"Extreme cold ({w.temperature_c:.0f}°C) strains the grid.")
        if w.temperature_c >= 38:
            notes.append(f"Extreme heat ({w.temperature_c:.0f}°C) strains the grid.")
        if not notes and hazard < 0.2:
            notes.append("Calm conditions — low weather-driven risk.")
        return notes
