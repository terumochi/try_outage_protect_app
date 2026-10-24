"""Customer-facing SMS message templates.

Two templates, per the agreed spec:
  - PRE_STORM_ALERT: elevated predicted risk, no confirmed outage yet.
  - OUTAGE_NOTIFICATION: an outage has been reported; restoration-focused.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from .service import Assessment

DEFAULT_UPDATE_SOURCE = "your utility provider's outage map"

PRE_STORM_ALERT = """\
Hello, {name}.

The current estimated power outage risk for your area is {band} (risk score: {score}/100).

Why: {risk_factors}

Recommended actions: {preparation_steps}

This is a prediction, not a confirmation that an outage will occur. Actual conditions may change as the storm develops.

For updates, check {update_source}."""

OUTAGE_NOTIFICATION = """\
Hello, {name}.

A power outage affecting your area has been reported.

**Estimated restoration window:** {earliest_time}–{latest_time}

**Current status:** {outage_status}

**Factors affecting restoration:** {restoration_factors}

This is an estimate, not a confirmed restoration time. The estimate may change as damage assessments and repair work progress.

For safety, stay away from downed power lines and report hazards to the appropriate utility or emergency service."""


def _risk_factors(assessment: Assessment) -> str:
    """Human-readable 'why' string from the top model contributions + notes."""
    contribs = assessment.prediction.contributions
    top = sorted(contribs.items(), key=lambda kv: kv[1], reverse=True)
    top_factors = [name for name, pts in top[:2] if pts > 0]
    parts: List[str] = []
    if top_factors:
        parts.append(", ".join(top_factors).lower())
    # Prepend the most specific weather notes, if any.
    notes = [n for n in assessment.prediction.notes if not n.startswith("Calm")]
    if notes:
        parts = notes[:2] + parts
    return "; ".join(parts) if parts else "elevated seasonal risk in your region"


def _preparation_steps(assessment: Assessment) -> str:
    """Recommended actions scaled to the risk band."""
    band = assessment.prediction.risk_band
    base = [
        "charge phones and backup batteries",
        "keep flashlights and water on hand",
    ]
    if band in ("High", "Severe"):
        base = [
            "charge all devices and backup batteries now",
            "prepare food/water for 24h",
            "keep a flashlight accessible and avoid using candles",
            "if you rely on medical equipment, arrange a backup power plan",
        ]
    return "; ".join(base)


def _restoration_factors(assessment: Assessment) -> str:
    notes = [n for n in assessment.prediction.notes if not n.startswith("Calm")]
    if notes:
        return "; ".join(notes[:3])
    return "crew availability and the extent of damage in your area"


def _outage_status(assessment: Assessment) -> str:
    band = assessment.prediction.risk_band
    if band in ("High", "Severe"):
        return "Crews are being dispatched; conditions in your area remain hazardous."
    return "Crews are assessing the affected area."


def render_pre_storm(assessment: Assessment, update_source: str = DEFAULT_UPDATE_SOURCE) -> str:
    p = assessment.prediction
    return PRE_STORM_ALERT.format(
        name=assessment.name,
        band=p.risk_band,
        score=p.risk_score,
        risk_factors=_risk_factors(assessment),
        preparation_steps=_preparation_steps(assessment),
        update_source=update_source,
    )


def render_outage(assessment: Assessment, now: datetime | None = None) -> str:
    """Render the post-outage restoration message.

    The restoration window is built from the model's estimated recovery hours,
    widened by +/-25% to communicate uncertainty.
    """
    now = now or datetime.now()
    hours = assessment.prediction.estimated_recovery_hours
    earliest = now + timedelta(hours=hours * 0.75)
    latest = now + timedelta(hours=hours * 1.25)
    fmt = "%a %I:%M %p"
    return OUTAGE_NOTIFICATION.format(
        name=assessment.name,
        earliest_time=earliest.strftime(fmt),
        latest_time=latest.strftime(fmt),
        outage_status=_outage_status(assessment),
        restoration_factors=_restoration_factors(assessment),
    )
