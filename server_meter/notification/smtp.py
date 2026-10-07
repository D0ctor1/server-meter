"""SMTP delivery. Timeouts are mandatory. Passwords are never logged."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from server_meter.config import AppConfig
from server_meter.notification.models import OutboundEmail

logger = logging.getLogger("server_meter.notification.smtp")


class SmtpError(Exception):
    """Safe SMTP error (no credentials)."""


def send_email(message: OutboundEmail, config: AppConfig) -> None:
    email_cfg = config.notifications.email
    smtp = email_cfg.smtp
    if not smtp.host:
        raise SmtpError("SMTP host is not configured")
    recipients = message.recipients or list(email_cfg.to)
    sender = message.from_address or email_cfg.from_address or smtp.username
    if not sender:
        raise SmtpError("SMTP sender address is not configured")
    if not recipients:
        raise SmtpError("SMTP recipient address is not configured")

    envelope = EmailMessage()
    envelope["Subject"] = message.subject
    envelope["From"] = sender
    envelope["To"] = ", ".join(recipients)
    envelope.set_content(message.body)

    timeout = smtp.timeout_seconds
    try:
        if smtp.security == "tls":
            with smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=timeout, context=ssl.create_default_context()) as client:
                _authenticate_and_send(client, smtp.username, smtp.password, sender, recipients, envelope)
        else:
            with smtplib.SMTP(smtp.host, smtp.port, timeout=timeout) as client:
                client.ehlo()
                if smtp.security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                _authenticate_and_send(client, smtp.username, smtp.password, sender, recipients, envelope)
    except SmtpError:
        raise
    except Exception as exc:
        raise SmtpError(_sanitize(str(exc), smtp.password)) from None


def _authenticate_and_send(client, username: str, password: str, sender: str, recipients: list[str], envelope: EmailMessage) -> None:
    if username:
        try:
            client.login(username, password)
        except smtplib.SMTPAuthenticationError:
            raise SmtpError("SMTP authentication failed") from None
    refused = client.send_message(envelope, from_addr=sender, to_addrs=recipients)
    if refused:
        raise SmtpError("SMTP server refused one or more recipients")


def _sanitize(text: str, password: str = "") -> str:
    cleaned = text
    if password:
        cleaned = cleaned.replace(password, "********")
    lowered = cleaned.lower()
    if "password" in lowered or "passwd" in lowered or "authentication" in lowered:
        return "SMTP authentication failed"
    return cleaned[:300]
