"""Email sending via SMTP for InvoicePilot."""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

logger = logging.getLogger("invoicepilot.email")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "invoices@invoicepilot.local")
FROM_NAME = os.environ.get("FROM_NAME", "InvoicePilot")


def is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    pdf_bytes: bytes | None = None,
    pdf_filename: str | None = None,
) -> bool:
    """Send an email. Returns True on success, False on failure."""
    if not is_configured():
        logger.warning("SMTP not configured, email not sent to %s: %s", to_email, subject)
        logger.info("Would send to: %s | Subject: %s", to_email, subject)
        return False

    msg = MIMEMultipart("mixed")
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = FROM_EMAIL

    html_part = MIMEText(html_body, "html", "utf-8")
    msg.attach(html_part)

    if pdf_bytes and pdf_filename:
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(pdf_part)

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        server.quit()
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)
        return False


def send_invoice_email(invoice: dict, html_body: str, pdf_bytes: bytes | None = None) -> bool:
    subject = f"Invoice {invoice['invoice_number']} from {FROM_NAME}"
    filename = f"{invoice['invoice_number']}.pdf" if pdf_bytes else None
    return send_email(invoice["client_email"], subject, html_body, pdf_bytes, filename)


def send_reminder_email(invoice: dict, subject: str, html_body: str) -> bool:
    return send_email(invoice["client_email"], subject, html_body)
