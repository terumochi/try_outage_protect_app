"""Notification orchestration: detect status changes and send SMS to customers.

Decides *whether* to notify (change detection against the persisted store),
*which* template to use (pre-storm alert vs. outage notification), and sends via
the configured SMS notifier.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import messages
from .notifier import SendResult, SMSNotifier
from .service import Assessment
from .status_store import StatusSnapshot, StatusStore

# Notify when the recovery estimate shifts by more than this many hours.
RECOVERY_DELTA_HOURS = 2.0


@dataclass
class NotificationDecision:
    address: str
    name: str
    should_notify: bool
    reason: str
    template: Optional[str]          # "pre_storm" | "outage" | None
    body: Optional[str] = None
    send_result: Optional[SendResult] = None


def _detect_change(
    assessment: Assessment,
    previous: Optional[StatusSnapshot],
    risk_threshold: float,
) -> tuple[bool, str, Optional[str]]:
    """Return (should_notify, reason, template)."""
    p = assessment.prediction

    # 1) A reported outage transition always wins -> restoration message.
    if assessment.outage_reported:
        was_outage = previous.outage_reported if previous else False
        if not was_outage:
            return True, "Outage newly reported.", "outage"
        # Already in outage: notify if the restoration estimate moved materially.
        if abs(p.estimated_recovery_hours - previous.estimated_recovery_hours) >= RECOVERY_DELTA_HOURS:
            return True, "Restoration estimate updated.", "outage"
        return False, "No material change since last outage update.", None

    # No active outage -> consider a pre-storm alert.
    elevated = p.risk_band in ("High", "Severe") or p.risk_score >= risk_threshold

    if previous is None:
        if elevated:
            return True, "First assessment: risk is elevated.", "pre_storm"
        return False, "First assessment: risk is low; no alert needed.", None

    # Band change.
    if p.risk_band != previous.risk_band:
        if elevated:
            return True, f"Risk band changed {previous.risk_band} -> {p.risk_band}.", "pre_storm"
        # Dropped to a calm band from an elevated one: send an all-clear-ish update.
        if previous.risk_band in ("High", "Severe"):
            return True, f"Risk eased {previous.risk_band} -> {p.risk_band}.", "pre_storm"

    # Significant recovery-estimate change while still elevated.
    if elevated and abs(p.estimated_recovery_hours - previous.estimated_recovery_hours) >= RECOVERY_DELTA_HOURS:
        return True, "Recovery-time estimate changed significantly.", "pre_storm"

    return False, "No notifiable change.", None


def process(
    assessments: List[Assessment],
    notifier: SMSNotifier,
    *,
    store: Optional[StatusStore] = None,
    risk_threshold: float = 50.0,
    update_source: str = messages.DEFAULT_UPDATE_SOURCE,
    dry_run: bool = False,
) -> List[NotificationDecision]:
    """Evaluate each assessment and send notifications for real changes.

    `dry_run=True` renders messages and records decisions but does not send,
    and does not advance the stored status (useful for previewing).
    """
    store = store or StatusStore()
    decisions: List[NotificationDecision] = []

    for a in assessments:
        previous = store.get(a.address)
        should, reason, template = _detect_change(a, previous, risk_threshold)

        decision = NotificationDecision(
            address=a.address, name=a.name, should_notify=should,
            reason=reason, template=template,
        )

        if should and template:
            if template == "pre_storm":
                decision.body = messages.render_pre_storm(a, update_source=update_source)
            else:
                decision.body = messages.render_outage(a)

            if not a.phone:
                decision.should_notify = False
                decision.reason = reason + " (skipped: no phone number on file)"
            elif not dry_run:
                decision.send_result = notifier.send(a.phone, decision.body)

        # Advance stored status unless this is a dry run.
        if not dry_run:
            store.set(
                a.address,
                StatusSnapshot(
                    risk_band=a.prediction.risk_band,
                    risk_score=a.prediction.risk_score,
                    estimated_recovery_hours=a.prediction.estimated_recovery_hours,
                    outage_reported=a.outage_reported,
                ),
            )

        decisions.append(decision)

    return decisions
