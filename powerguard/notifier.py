"""SMS notifier abstraction with a zero-config mock and an opt-in Twilio sender.

Consistent with the app's offline-first design: the MockSMSNotifier logs the
message (and records it for the UI) so everything runs with no accounts. The
TwilioSMSNotifier sends real SMS when credentials are present in the
environment.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger("powerguard.notifier")


@dataclass
class SendResult:
    to: str
    body: str
    channel: str
    success: bool
    detail: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class SMSNotifier(ABC):
    channel = "sms"

    @abstractmethod
    def send(self, to: str, body: str) -> SendResult:  # pragma: no cover - interface
        ...


class MockSMSNotifier(SMSNotifier):
    """Default sender: records messages instead of transmitting them."""

    channel = "sms:mock"

    def __init__(self) -> None:
        self.sent: List[SendResult] = []

    def send(self, to: str, body: str) -> SendResult:
        result = SendResult(
            to=to, body=body, channel=self.channel, success=True, detail="logged (mock)"
        )
        self.sent.append(result)
        logger.info("[MOCK SMS] -> %s\n%s", to, body)
        return result


class TwilioSMSNotifier(SMSNotifier):
    """Real SMS via Twilio. Enabled only when credentials are configured.

    Reads TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER from the
    environment. Requires the `twilio` package (not installed by default).
    """

    channel = "sms:twilio"

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
    ) -> None:
        self.account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_number = from_number or os.environ.get("TWILIO_FROM_NUMBER")
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise ValueError(
                "Twilio not configured: set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                "and TWILIO_FROM_NUMBER."
            )
        self.sent: List[SendResult] = []

    def send(self, to: str, body: str) -> SendResult:
        try:
            from twilio.rest import Client  # imported lazily; optional dependency
        except ImportError:
            result = SendResult(
                to=to, body=body, channel=self.channel, success=False,
                detail="twilio package not installed (pip install twilio)",
            )
            self.sent.append(result)
            return result

        try:
            client = Client(self.account_sid, self.auth_token)
            msg = client.messages.create(body=body, from_=self.from_number, to=to)
            result = SendResult(
                to=to, body=body, channel=self.channel, success=True, detail=f"sid={msg.sid}"
            )
        except Exception as exc:  # noqa: BLE001 - surface any provider error to UI
            result = SendResult(
                to=to, body=body, channel=self.channel, success=False, detail=str(exc)
            )
        self.sent.append(result)
        return result


def build_notifier(use_twilio: bool = False) -> SMSNotifier:
    """Factory: Twilio if requested and configured, else the mock sender."""
    if use_twilio:
        return TwilioSMSNotifier()
    return MockSMSNotifier()
