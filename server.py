"""InvoicePilot - Smart Invoicing Service with Auto-Chase Reminders."""

import os
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from jinja2 import Environment, FileSystemLoader, select_autoescape

import db
from calculator import (
    calculate_invoice_totals,
    days_overdue,
    format_currency,
)
from pdf_gen import generate_invoice_pdf
from email_sender import send_invoice_email, is_configured as smtp_configured
from reminders import start_scheduler, stop_scheduler, manually_send_reminder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("invoicepilot")

template_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)

FREE_TIER_LIMIT = 5
REMINDER_INTERVAL = int(os.environ.get("REMINDER_INTERVAL_MINUTES", "60"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Database initialized")
    start_scheduler(REMINDER_INTERVAL)
    yield
    stop_scheduler()


app = FastAPI(
    title="InvoicePilot",
    description="Smart invoicing service with auto-chase payment reminders",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic models ---

class LineItem(BaseModel):
    description: str
    qty: float = 1
    rate: float = 0


class InvoiceCreate(BaseModel):
    client_name: str
    client_email: str
    items: list[LineItem]
    due_date: str = Field(..., description="ISO date string YYYY-MM-DD")
    currency: str = "USD"
    tax_rate: float = 0
    notes: str | None = None
    payment_link: str | None = None
    late_fee_percent: float = 0


class InvoiceUpdate(BaseModel):
    client_name: str | None = None
    client_email: str | None = None
    items: list[LineItem] | None = None
    due_date: str | None = None
    currency: str | None = None
    tax_rate: float | None = None
    notes: str | None = None
    payment_link: str | None = None
    late_fee_percent: float | None = None


# --- Helper ---

def check_free_tier():
    count = db.get_invoices_this_month_count()
    limit = int(db.get_setting("free_tier_limit", str(FREE_TIER_LIMIT)))
    if count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Free tier limit reached ({limit} invoices/month). Upgrade for unlimited.",
        )


# --- Invoice CRUD ---

@app.post("/invoices", status_code=201)
def create_invoice(body: InvoiceCreate):
    check_free_tier()
    items = [i.model_dump() for i in body.items]
    totals = calculate_invoice_totals(items, body.tax_rate)
    data = {
        "client_name": body.client_name,
        "client_email": body.client_email,
        "items": items,
        "due_date": body.due_date,
        "currency": body.currency,
        "notes": body.notes,
        "payment_link": body.payment_link,
        "late_fee_percent": body.late_fee_percent,
        **totals,
    }
    invoice = db.create_invoice(data)
    return invoice


@app.get("/invoices")
def list_invoices(
    status: str | None = Query(None, description="Filter by status"),
    client_email: str | None = Query(None),
):
    return db.list_invoices(status=status, client_email=client_email)


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int):
    inv = db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@app.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, body: InvoiceUpdate):
    existing = db.get_invoice(invoice_id)
    if not existing:
        raise HTTPException(404, "Invoice not found")
    if existing["status"] == "paid":
        raise HTTPException(400, "Cannot update a paid invoice")

    update_data = body.model_dump(exclude_none=True)

    # Recalculate totals if items or tax_rate changed
    if "items" in update_data or "tax_rate" in update_data:
        items = [i.model_dump() for i in body.items] if body.items else existing["items"]
        tax_rate = update_data.get("tax_rate", existing["tax_rate"])
        totals = calculate_invoice_totals(items, tax_rate, existing.get("late_fee_applied", 0))
        update_data.update(totals)
        if body.items:
            update_data["items"] = items

    result = db.update_invoice(invoice_id, update_data)
    return result


@app.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int):
    if not db.delete_invoice(invoice_id):
        raise HTTPException(404, "Invoice not found")
    return {"status": "deleted", "id": invoice_id}


# --- Invoice Actions ---

@app.post("/invoices/{invoice_id}/send")
def send_invoice(invoice_id: int):
    inv = db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv["status"] == "paid":
        raise HTTPException(400, "Invoice is already paid")

    company_name = db.get_setting("company_name", "InvoicePilot")
    currency = inv.get("currency", "USD")
    total_fmt = format_currency(inv["total"], currency)

    # Render email
    tmpl = template_env.get_template("invoice_email.html")
    html = tmpl.render(
        company_name=company_name,
        client_name=inv["client_name"],
        invoice_number=inv["invoice_number"],
        created_date=inv["created_at"][:10],
        due_date=inv["due_date"][:10],
        total=total_fmt,
        payment_link=inv.get("payment_link"),
        notes=inv.get("notes"),
        tracking_url=None,
    )

    # Generate PDF attachment
    pdf_bytes = generate_invoice_pdf(inv, company_name)

    # Send email
    email_sent = send_invoice_email(inv, html, pdf_bytes)

    # Update status
    now = datetime.now(timezone.utc).isoformat()
    db.update_invoice(invoice_id, {"status": "sent", "sent_at": now})

    return {
        "status": "sent",
        "email_sent": email_sent,
        "smtp_configured": smtp_configured(),
        "invoice_number": inv["invoice_number"],
    }


@app.post("/invoices/{invoice_id}/mark-paid")
def mark_paid(invoice_id: int):
    inv = db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv["status"] == "paid":
        return {"status": "already_paid", "invoice_number": inv["invoice_number"]}

    now = datetime.now(timezone.utc).isoformat()
    db.update_invoice(invoice_id, {"status": "paid", "paid_at": now})
    return {"status": "paid", "invoice_number": inv["invoice_number"], "paid_at": now}


@app.post("/invoices/{invoice_id}/remind")
def send_reminder(invoice_id: int):
    result = manually_send_reminder(invoice_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# --- PDF ---

@app.get("/invoices/{invoice_id}/pdf")
def get_invoice_pdf(invoice_id: int):
    inv = db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")

    company_name = db.get_setting("company_name", "InvoicePilot")
    company_address = db.get_setting("company_address", "")
    pdf_bytes = generate_invoice_pdf(inv, company_name, company_address)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{inv["invoice_number"]}.pdf"'
        },
    )


# --- Client-Facing Payment Page ---

@app.get("/invoices/{invoice_id}/pay", response_class=HTMLResponse)
def payment_page(invoice_id: int):
    inv = db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")

    company_name = db.get_setting("company_name", "InvoicePilot")
    currency = inv.get("currency", "USD")
    overdue = days_overdue(inv["due_date"])

    def fmt(amount):
        return format_currency(amount, currency)

    tmpl = template_env.get_template("payment_page.html")
    html = tmpl.render(
        company_name=company_name,
        invoice_number=inv["invoice_number"],
        client_name=inv["client_name"],
        created_date=inv["created_at"][:10],
        due_date=inv["due_date"][:10],
        status=inv["status"],
        items=inv["items"],
        subtotal_fmt=fmt(inv["subtotal"]),
        tax_rate=inv["tax_rate"],
        tax_fmt=fmt(inv["tax"]),
        late_fee_applied=inv.get("late_fee_applied", 0),
        late_fee_fmt=fmt(inv.get("late_fee_applied", 0)),
        total=fmt(inv["total"]),
        payment_link=inv.get("payment_link"),
        notes=inv.get("notes"),
        days_overdue=overdue,
        format_currency=fmt,
    )
    return HTMLResponse(html)


# --- Dashboard & Clients ---

@app.get("/dashboard")
def dashboard():
    return db.get_dashboard_stats()


@app.get("/clients")
def list_clients():
    return db.get_unique_clients()


# --- Tracking pixel (for email open tracking) ---

@app.get("/track/{reminder_id}.png")
def track_open(reminder_id: int):
    db.mark_reminder_opened(reminder_id)
    # 1x1 transparent PNG
    pixel = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(content=pixel, media_type="image/png")


# --- Health ---

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "InvoicePilot",
        "version": "1.0.0",
        "smtp_configured": smtp_configured(),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8450"))
    uvicorn.run(app, host="0.0.0.0", port=port)
