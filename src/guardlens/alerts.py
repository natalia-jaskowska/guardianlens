"""Parent notification dispatch.

Three channels, all off by default:

- **Email** via SMTP (``smtplib`` from the standard library).
- **Webhook** via a simple POST (intended for IFTTT/Zapier/Discord-bot etc.).
- **Telegram** via the official Bot API — a real push notification to the
  parent's phone. This is the one shown in the video demo.

All channels respect ``AlertConfig.minimum_urgency`` so we never spam the
parent over caution-level findings. The actual model output (raw chat text)
is never included in the notification — only the high-level fields from
:class:`ParentAlert`.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from guardlens.config import AlertConfig
from guardlens.schema import AlertUrgency, ParentAlert, ScreenAnalysis

logger = logging.getLogger(__name__)


# Lower index = lower urgency. Used to compare against the configured threshold.
_URGENCY_ORDER: dict[AlertUrgency, int] = {
    AlertUrgency.LOW: 0,
    AlertUrgency.MEDIUM: 1,
    AlertUrgency.HIGH: 2,
    AlertUrgency.IMMEDIATE: 3,
}


class AlertSender:
    """Dispatch :class:`ParentAlert` objects through configured channels."""

    def __init__(self, config: AlertConfig) -> None:
        self.config = config
        try:
            self._threshold = AlertUrgency(config.minimum_urgency)
        except ValueError:
            logger.warning(
                "Invalid minimum_urgency %r, defaulting to HIGH",
                config.minimum_urgency,
            )
            self._threshold = AlertUrgency.HIGH

    # ------------------------------------------------------------------ public

    def maybe_send(self, analysis: ScreenAnalysis) -> bool:
        """Send a notification if the analysis meets the minimum urgency.

        Returns ``True`` if at least one channel actually fired.
        """
        alert = analysis.parent_alert
        if alert is None:
            return False
        if not self._meets_threshold(alert.urgency):
            return False

        sent = False
        if self.config.enable_email:
            sent |= self._send_email(alert)
        if self.config.enable_webhook:
            sent |= self._send_webhook(alert)
        if self.config.enable_telegram:
            sent |= self._send_telegram(alert)
        return sent

    # ------------------------------------------------------------------ helpers

    def _meets_threshold(self, urgency: AlertUrgency) -> bool:
        return _URGENCY_ORDER[urgency] >= _URGENCY_ORDER[self._threshold]

    def _send_email(self, alert: ParentAlert) -> bool:
        if not (self.config.smtp_host and self.config.parent_email):
            logger.warning("Email enabled but SMTP host / parent_email missing.")
            return False
        msg = EmailMessage()
        msg["Subject"] = f"[GuardianLens] {alert.alert_title}"
        msg["From"] = self.config.smtp_user or "guardianlens@localhost"
        msg["To"] = self.config.parent_email
        msg.set_content(
            f"{alert.summary}\n\n"
            f"Recommended action: {alert.recommended_action}\n"
            f"Urgency: {alert.urgency.value}\n"
        )
        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as smtp:
                smtp.starttls()
                if self.config.smtp_user and self.config.smtp_password:
                    smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("Failed to send email alert: %s", exc)
            return False
        return True

    def _send_webhook(self, alert: ParentAlert) -> bool:
        if not self.config.webhook_url:
            logger.warning("Webhook enabled but webhook_url is empty.")
            return False
        payload = json.dumps(alert.model_dump(mode="json")).encode("utf-8")
        request = urllib.request.Request(
            self.config.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, OSError) as exc:
            logger.error("Failed to POST webhook alert: %s", exc)
            return False

    def _send_telegram(self, alert: ParentAlert) -> bool:
        """POST to the Telegram Bot API ``sendMessage`` endpoint.

        The body is intentionally simple — privacy-safe Markdown that
        includes threat_type, platform (from the caller), confidence,
        indicator labels, and recommended action, and nothing else. Raw
        chat text never appears here because :class:`ParentAlert` itself
        does not carry it.
        """
        token = self.config.telegram_bot_token
        chat_id = self.config.telegram_chat_id
        if not token or not chat_id:
            logger.warning(
                "Telegram enabled but bot token or chat_id missing — skipping send."
            )
            return False

        text = format_telegram_message(alert)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                ok = 200 <= response.status < 300
                if ok:
                    logger.info(
                        "Telegram alert delivered (urgency=%s, title=%r)",
                        alert.urgency.value,
                        alert.alert_title,
                    )
                else:
                    logger.error(
                        "Telegram alert returned HTTP %s", response.status
                    )
                return ok
        except (urllib.error.URLError, OSError) as exc:
            logger.error("Failed to POST Telegram alert: %s", exc)
            return False


def format_telegram_message(alert: ParentAlert) -> str:
    """Render a :class:`ParentAlert` into privacy-safe Telegram Markdown.

    Kept as a module-level function so it can be unit-tested without
    spinning up the whole :class:`AlertSender`.
    """
    urgency_icon = {
        AlertUrgency.LOW: "🟢",
        AlertUrgency.MEDIUM: "🟡",
        AlertUrgency.HIGH: "🟠",
        AlertUrgency.IMMEDIATE: "🔴",
    }.get(alert.urgency, "🔔")

    return (
        f"{urgency_icon} *GuardianLens Alert*\n\n"
        f"*{_escape_md(alert.alert_title)}*\n\n"
        f"{_escape_md(alert.summary)}\n\n"
        f"*Recommended:* {_escape_md(alert.recommended_action)}\n\n"
        f"_No chat content shared. AI analysis only._"
    )


def _escape_md(text: str) -> str:
    """Escape the handful of Markdown v1 control chars Telegram cares about."""
    if not text:
        return ""
    out = text
    for ch in ("_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out
