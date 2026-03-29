"""MCP Server for InvoicePilot - exposes invoicing tools to AI assistants."""

import os
import json
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

import db
from calculator import (
    calculate_invoice_totals,
    days_overdue,
    format_currency,
)
from reminders import manually_send_reminder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("invoicepilot.mcp")

mcp = FastMCP(
    "InvoicePilot",
    description="Smart invoicing service with auto-chase payment reminders",
)


@mcp.tool()
def create_invoice(
    client_name: str,
    client_email: str,
    items: list[dict],
    due_date: str,
    currency: str = "USD",
    tax_rate: float = 0,
    notes: str | None = None,
    payment_link: str | None = None,
    late_fee_percent: float = 0,
    send_immediately: bool = False,
) -> str:
    """Create a new invoice. Items should be list of {description, qty, rate}.
    Set send_immediately=True to email the invoice to the client right away.

    Args:
        client_name: Name of the client
        client_email: Client's email address
        items: Line items as list of dicts with description, qty, rate
        due_date: Due date in YYYY-MM-DD format
        currency: Currency code (USD, EUR, GBP, etc.)
        tax_rate: Tax percentage to apply (e.g. 10 for 10%)
        notes: Optional notes to include on the invoice
        payment_link: URL where client can pay
        late_fee_percent: Late fee percentage to apply when overdue
        send_immediately: Whether to email the invoice right away
    """
    db.init_db()

    # Check free tier
    count = db.get_invoices_this_month_count()
    limit = int(db.get_setting("free_tier_limit", "5"))
    if count >= limit:
        return f"Free tier limit reached ({limit} invoices/month). Upgrade for unlimited."

    totals = calculate_invoice_totals(items, tax_rate)
    data = {
        "client_name": client_name,
        "client_email": client_email,
        "items": items,
        "due_date": due_date,
        "currency": currency,
        "notes": notes,
        "payment_link": payment_link,
        "late_fee_percent": late_fee_percent,
        **totals,
    }
    invoice = db.create_invoice(data)

    if send_immediately:
        db.update_invoice(invoice["id"], {
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })

    total_fmt = format_currency(invoice["total"], currency)
    result = (
        f"Invoice {invoice['invoice_number']} created for {client_name} ({client_email})\n"
        f"Total: {total_fmt} | Due: {due_date} | Status: {'sent' if send_immediately else 'draft'}\n"
        f"Items: {len(items)} line items"
    )
    return result


@mcp.tool()
def list_invoices(status: str | None = None) -> str:
    """List all invoices, optionally filtered by status (draft/sent/overdue/paid).

    Args:
        status: Optional filter - one of: draft, sent, overdue, paid
    """
    db.init_db()
    invoices = db.list_invoices(status=status)

    if not invoices:
        return f"No invoices found{f' with status={status}' if status else ''}."

    lines = [f"Found {len(invoices)} invoice(s):\n"]
    for inv in invoices:
        currency = inv.get("currency", "USD")
        total_fmt = format_currency(inv["total"], currency)
        overdue = days_overdue(inv["due_date"])
        overdue_str = f" ({overdue}d overdue)" if overdue > 0 and inv["status"] != "paid" else ""
        lines.append(
            f"  {inv['invoice_number']} | {inv['client_name']} | "
            f"{total_fmt} | {inv['status'].upper()}{overdue_str} | Due: {inv['due_date'][:10]}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_outstanding() -> str:
    """Show all unpaid invoices with amounts and days overdue."""
    db.init_db()
    invoices = db.list_invoices()
    unpaid = [inv for inv in invoices if inv["status"] in ("sent", "overdue")]

    if not unpaid:
        return "No outstanding invoices. All caught up!"

    total_outstanding = 0
    lines = [f"{len(unpaid)} outstanding invoice(s):\n"]
    for inv in unpaid:
        currency = inv.get("currency", "USD")
        total_fmt = format_currency(inv["total"], currency)
        overdue = days_overdue(inv["due_date"])
        total_outstanding += inv["total"]
        status_label = f"OVERDUE ({overdue}d)" if overdue > 0 else "PENDING"
        lines.append(
            f"  {inv['invoice_number']} | {inv['client_name']} | "
            f"{total_fmt} | {status_label} | Due: {inv['due_date'][:10]}"
        )

    lines.append(f"\nTotal outstanding: {format_currency(total_outstanding, 'USD')}")
    return "\n".join(lines)


@mcp.tool()
def send_reminder(invoice_id: int) -> str:
    """Manually trigger a payment reminder for an overdue invoice.

    Args:
        invoice_id: The ID of the invoice to send a reminder for
    """
    db.init_db()
    result = manually_send_reminder(invoice_id)
    if "error" in result:
        return f"Error: {result['error']}"
    return (
        f"Reminder sent for invoice #{invoice_id}\n"
        f"Level: {result['level']} ({result['level_name']})\n"
        f"Status: {result['status']}"
    )


@mcp.tool()
def mark_paid(invoice_id: int) -> str:
    """Mark an invoice as paid.

    Args:
        invoice_id: The ID of the invoice to mark as paid
    """
    db.init_db()
    inv = db.get_invoice(invoice_id)
    if not inv:
        return f"Error: Invoice #{invoice_id} not found."
    if inv["status"] == "paid":
        return f"Invoice {inv['invoice_number']} is already marked as paid."

    now = datetime.now(timezone.utc).isoformat()
    db.update_invoice(invoice_id, {"status": "paid", "paid_at": now})
    total_fmt = format_currency(inv["total"], inv.get("currency", "USD"))
    return (
        f"Invoice {inv['invoice_number']} marked as PAID\n"
        f"Client: {inv['client_name']} | Amount: {total_fmt} | Paid at: {now[:10]}"
    )


@mcp.tool()
def get_revenue_summary() -> str:
    """Get revenue summary: total revenue, outstanding amounts, overdue amounts, this month stats."""
    db.init_db()
    stats = db.get_dashboard_stats()
    return (
        f"Revenue Summary:\n"
        f"  Total Revenue (all time): {format_currency(stats['total_revenue']['amount'], 'USD')} "
        f"({stats['total_revenue']['count']} invoices)\n"
        f"  Paid This Month: {format_currency(stats['paid_this_month']['amount'], 'USD')} "
        f"({stats['paid_this_month']['count']} invoices)\n"
        f"  Outstanding: {format_currency(stats['outstanding']['amount'], 'USD')} "
        f"({stats['outstanding']['count']} invoices)\n"
        f"  Overdue: {format_currency(stats['overdue']['amount'], 'USD')} "
        f"({stats['overdue']['count']} invoices)\n"
        f"  Total Invoices: {stats['total_invoices']} "
        f"({stats['invoices_this_month']} this month)"
    )


if __name__ == "__main__":
    db.init_db()
    mcp.run()
