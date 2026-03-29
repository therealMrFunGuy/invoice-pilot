"""Tax, late fee, and total calculations for InvoicePilot."""

from datetime import datetime, timezone


def calculate_line_total(qty: float, rate: float) -> float:
    return round(qty * rate, 2)


def calculate_subtotal(items: list[dict]) -> float:
    total = 0.0
    for item in items:
        total += calculate_line_total(item.get("qty", 0), item.get("rate", 0))
    return round(total, 2)


def calculate_tax(subtotal: float, tax_rate: float) -> float:
    return round(subtotal * (tax_rate / 100.0), 2)


def calculate_total(subtotal: float, tax: float, late_fee: float = 0) -> float:
    return round(subtotal + tax + late_fee, 2)


def calculate_invoice_totals(items: list[dict], tax_rate: float = 0, late_fee_applied: float = 0) -> dict:
    subtotal = calculate_subtotal(items)
    tax = calculate_tax(subtotal, tax_rate)
    total = calculate_total(subtotal, tax, late_fee_applied)
    return {
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax": tax,
        "late_fee_applied": late_fee_applied,
        "total": total,
    }


def calculate_late_fee(subtotal: float, late_fee_percent: float) -> float:
    if late_fee_percent <= 0:
        return 0.0
    return round(subtotal * (late_fee_percent / 100.0), 2)


def days_overdue(due_date_str: str) -> int:
    try:
        due = datetime.fromisoformat(due_date_str)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (now - due).days
        return max(0, delta)
    except (ValueError, TypeError):
        return 0


def determine_reminder_level(overdue_days: int) -> int | None:
    """Return reminder level based on days overdue, or None if no reminder needed."""
    if overdue_days >= 30:
        return 4  # Final warning
    elif overdue_days >= 14:
        return 3  # Late fee notice
    elif overdue_days >= 7:
        return 2  # Firm reminder
    elif overdue_days >= 1:
        return 1  # Friendly reminder
    return None


REMINDER_LEVELS = {
    1: {"name": "friendly", "subject": "Friendly Payment Reminder", "template": "reminder_friendly.html"},
    2: {"name": "firm", "subject": "Payment Reminder - Action Required", "template": "reminder_firm.html"},
    3: {"name": "late_fee", "subject": "Late Fee Notice - Payment Overdue", "template": "reminder_firm.html"},
    4: {"name": "final", "subject": "Final Notice - Immediate Payment Required", "template": "reminder_final.html"},
}


def format_currency(amount: float, currency: str = "USD") -> str:
    symbols = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "CAD": "CA$", "AUD": "A$"}
    sym = symbols.get(currency, currency + " ")
    return f"{sym}{amount:,.2f}"
