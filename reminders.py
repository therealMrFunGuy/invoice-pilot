"""Auto-reminder scheduler for overdue invoices."""

import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jinja2 import Environment, FileSystemLoader, select_autoescape

import db
from calculator import (
    days_overdue,
    determine_reminder_level,
    calculate_late_fee,
    format_currency,
    REMINDER_LEVELS,
)
from email_sender import send_reminder_email

logger = logging.getLogger("invoicepilot.reminders")

template_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)

scheduler = AsyncIOScheduler()


def process_overdue_invoices():
    """Check all overdue invoices and send appropriate reminders."""
    logger.info("Running overdue invoice check...")
    invoices = db.list_invoices()
    now = datetime.now(timezone.utc)
    sent_count = 0

    for inv in invoices:
        if inv["status"] in ("paid", "draft"):
            continue

        overdue = days_overdue(inv["due_date"])
        if overdue <= 0:
            continue

        # Mark as overdue if still 'sent'
        if inv["status"] == "sent":
            db.update_invoice(inv["id"], {"status": "overdue"})
            inv["status"] = "overdue"

        # Determine what reminder level we should be at
        target_level = determine_reminder_level(overdue)
        if target_level is None:
            continue

        # Check last reminder sent
        last_reminder = db.get_last_reminder(inv["id"])
        if last_reminder and last_reminder["level"] >= target_level:
            continue  # Already sent this level or higher

        # Apply late fee at level 3+
        if target_level >= 3 and inv.get("late_fee_percent", 0) > 0 and inv.get("late_fee_applied", 0) == 0:
            late_fee = calculate_late_fee(inv["subtotal"], inv["late_fee_percent"])
            new_total = round(inv["total"] + late_fee, 2)
            db.update_invoice(inv["id"], {
                "late_fee_applied": late_fee,
                "total": new_total,
            })
            inv["late_fee_applied"] = late_fee
            inv["total"] = new_total
            logger.info("Applied late fee of %s to invoice %s", late_fee, inv["invoice_number"])

        # Send reminder
        level_info = REMINDER_LEVELS.get(target_level, REMINDER_LEVELS[1])
        success = send_invoice_reminder(inv, target_level, level_info, overdue)

        if success:
            db.add_reminder(inv["id"], target_level, level_info["name"])
            sent_count += 1
            logger.info(
                "Sent %s reminder for invoice %s (%d days overdue)",
                level_info["name"], inv["invoice_number"], overdue,
            )
        else:
            # Still record the reminder attempt even if email fails (SMTP not configured)
            db.add_reminder(inv["id"], target_level, level_info["name"])
            sent_count += 1

    logger.info("Overdue check complete. %d reminders processed.", sent_count)
    return sent_count


def send_invoice_reminder(invoice: dict, level: int, level_info: dict, overdue: int) -> bool:
    """Render and send a reminder email for an invoice."""
    company_name = db.get_setting("company_name", "InvoicePilot")
    currency = invoice.get("currency", "USD")
    total_fmt = format_currency(invoice["total"], currency)

    template_name = level_info["template"]
    try:
        tmpl = template_env.get_template(template_name)
    except Exception:
        tmpl = template_env.get_template("reminder_friendly.html")

    # Build late fee notice text
    late_fee_notice = None
    if level >= 3 and invoice.get("late_fee_applied", 0) > 0:
        fee_fmt = format_currency(invoice["late_fee_applied"], currency)
        late_fee_notice = (
            f"A late fee of {fee_fmt} ({invoice.get('late_fee_percent', 0)}%) "
            f"has been applied to this invoice."
        )

    original_total = None
    if invoice.get("late_fee_applied", 0) > 0:
        original_total = format_currency(
            invoice["total"] - invoice["late_fee_applied"], currency
        )

    html = tmpl.render(
        company_name=company_name,
        client_name=invoice["client_name"],
        invoice_number=invoice["invoice_number"],
        due_date=invoice["due_date"][:10],
        created_date=invoice.get("created_at", "")[:10],
        days_overdue=overdue,
        total=total_fmt,
        original_total=original_total,
        payment_link=invoice.get("payment_link"),
        late_fee_notice=late_fee_notice,
        reminder_count=len(invoice.get("reminders", [])),
        tracking_url=None,
    )

    return send_reminder_email(invoice, level_info["subject"], html)


def manually_send_reminder(invoice_id: int) -> dict:
    """Manually trigger a reminder for a specific invoice."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        return {"error": "Invoice not found"}
    if invoice["status"] == "paid":
        return {"error": "Invoice is already paid"}

    overdue = days_overdue(invoice["due_date"])
    if overdue <= 0:
        return {"error": "Invoice is not overdue"}

    target_level = determine_reminder_level(overdue)
    if target_level is None:
        target_level = 1

    level_info = REMINDER_LEVELS.get(target_level, REMINDER_LEVELS[1])
    send_invoice_reminder(invoice, target_level, level_info, overdue)
    reminder = db.add_reminder(invoice["id"], target_level, level_info["name"])

    return {
        "status": "sent",
        "level": target_level,
        "level_name": level_info["name"],
        "reminder": reminder,
    }


def start_scheduler(interval_minutes: int = 60):
    """Start the background scheduler for checking overdue invoices."""
    scheduler.add_job(
        process_overdue_invoices,
        "interval",
        minutes=interval_minutes,
        id="overdue_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Reminder scheduler started (interval: %d min)", interval_minutes)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Reminder scheduler stopped")
