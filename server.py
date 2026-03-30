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


# --- Landing Page ---

@app.get("/", response_class=HTMLResponse)
def landing_page():
    return HTMLResponse(LANDING_HTML)


LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>InvoicePilot - Smart Invoicing with Auto-Chase Reminders</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  .code-block { background: #1e293b; color: #e2e8f0; border-radius: 0.5rem; padding: 1.25rem; overflow-x: auto; font-size: 0.85rem; line-height: 1.6; }
  .code-block .comment { color: #64748b; }
  .code-block .string { color: #7dd3fc; }
  .code-block .key { color: #38bdf8; }
</style>
</head>
<body class="bg-white text-gray-900 antialiased">

<!-- Nav -->
<nav class="sticky top-0 z-50 bg-white/80 backdrop-blur border-b border-gray-100">
  <div class="max-w-6xl mx-auto flex items-center justify-between px-6 py-4">
    <div class="flex items-center gap-2">
      <svg class="w-8 h-8 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
      <span class="text-xl font-bold text-gray-900">InvoicePilot</span>
    </div>
    <div class="hidden md:flex items-center gap-8 text-sm font-medium text-gray-600">
      <a href="#features" class="hover:text-sky-600 transition">Features</a>
      <a href="#pricing" class="hover:text-sky-600 transition">Pricing</a>
      <a href="#api" class="hover:text-sky-600 transition">Docs</a>
      <a href="https://github.com/therealMrFunGuy/invoice-pilot" target="_blank" class="hover:text-sky-600 transition">GitHub</a>
    </div>
  </div>
</nav>

<!-- Hero -->
<section class="relative overflow-hidden bg-gradient-to-br from-sky-50 via-white to-blue-50 py-24 lg:py-32">
  <div class="max-w-4xl mx-auto px-6 text-center">
    <span class="inline-block px-3 py-1 text-xs font-semibold text-sky-700 bg-sky-100 rounded-full mb-6">MCP-native invoicing</span>
    <h1 class="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-gray-900 leading-tight">
      Smart Invoicing with<br/><span class="text-sky-500">Auto-Chase Reminders</span>
    </h1>
    <p class="mt-6 text-lg text-gray-500 max-w-2xl mx-auto">
      Generate professional PDF invoices, track payments in real time, and let escalating auto-reminders chase late payers for you. Plug it into any LLM workflow via MCP.
    </p>
    <div class="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
      <a href="#api" class="px-6 py-3 rounded-lg bg-sky-500 text-white font-semibold shadow hover:bg-sky-600 transition">View API Docs</a>
      <a href="https://github.com/therealMrFunGuy/invoice-pilot" target="_blank" class="px-6 py-3 rounded-lg border border-gray-300 font-semibold hover:border-sky-400 hover:text-sky-600 transition">GitHub Repo</a>
    </div>
  </div>
</section>

<!-- Code Examples -->
<section class="py-20 bg-gray-50">
  <div class="max-w-5xl mx-auto px-6">
    <h2 class="text-3xl font-bold text-center mb-4">Get Started in Seconds</h2>
    <p class="text-center text-gray-500 mb-12">Use curl, any HTTP client, or wire it up as an MCP server.</p>
    <div class="grid md:grid-cols-2 gap-8">
      <div>
        <h3 class="text-sm font-semibold text-sky-600 uppercase tracking-wide mb-3">Create &amp; Send an Invoice</h3>
        <div class="code-block">
<span class="comment"># Create an invoice</span>
curl -X POST /invoices \\
  -H "Content-Type: application/json" \\
  -d '{
    <span class="key">"client_name"</span>: <span class="string">"Acme Corp"</span>,
    <span class="key">"client_email"</span>: <span class="string">"billing@acme.co"</span>,
    <span class="key">"due_date"</span>: <span class="string">"2026-04-15"</span>,
    <span class="key">"items"</span>: [
      {<span class="key">"description"</span>: <span class="string">"Consulting"</span>, <span class="key">"qty"</span>: 10, <span class="key">"rate"</span>: 150}
    ]
  }'

<span class="comment"># Send it (email + PDF attachment)</span>
curl -X POST /invoices/1/send

<span class="comment"># Download PDF</span>
curl -O /invoices/1/pdf
        </div>
      </div>
      <div>
        <h3 class="text-sm font-semibold text-sky-600 uppercase tracking-wide mb-3">MCP Configuration</h3>
        <div class="code-block">
<span class="comment">// claude_desktop_config.json</span>
{
  <span class="key">"mcpServers"</span>: {
    <span class="key">"invoicepilot"</span>: {
      <span class="key">"command"</span>: <span class="string">"uvx"</span>,
      <span class="key">"args"</span>: [
        <span class="string">"mcp-server-invoicepilot"</span>
      ],
      <span class="key">"env"</span>: {
        <span class="key">"SMTP_HOST"</span>: <span class="string">"smtp.gmail.com"</span>,
        <span class="key">"SMTP_USER"</span>: <span class="string">"you@example.com"</span>,
        <span class="key">"SMTP_PASS"</span>: <span class="string">"app-password"</span>
      }
    }
  }
}
        </div>
      </div>
    </div>
  </div>
</section>

<!-- Features -->
<section id="features" class="py-20">
  <div class="max-w-6xl mx-auto px-6">
    <h2 class="text-3xl font-bold text-center mb-4">Everything You Need</h2>
    <p class="text-center text-gray-500 mb-14">From creation to collection, InvoicePilot handles the full lifecycle.</p>
    <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">
      <!-- Card 1 -->
      <div class="p-6 rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition">
        <div class="w-12 h-12 flex items-center justify-center rounded-lg bg-sky-50 text-sky-500 mb-4">
          <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
        </div>
        <h3 class="font-semibold text-lg mb-2">PDF Generation</h3>
        <p class="text-gray-500 text-sm">Professional invoices rendered to PDF with line items, tax, late fees, and your company branding.</p>
      </div>
      <!-- Card 2 -->
      <div class="p-6 rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition">
        <div class="w-12 h-12 flex items-center justify-center rounded-lg bg-amber-50 text-amber-500 mb-4">
          <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>
        </div>
        <h3 class="font-semibold text-lg mb-2">Auto-Chase Reminders</h3>
        <p class="text-gray-500 text-sm">Escalating email reminders that get progressively firmer: friendly, firm, urgent, and final notice.</p>
      </div>
      <!-- Card 3 -->
      <div class="p-6 rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition">
        <div class="w-12 h-12 flex items-center justify-center rounded-lg bg-green-50 text-green-500 mb-4">
          <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        </div>
        <h3 class="font-semibold text-lg mb-2">Payment Tracking</h3>
        <p class="text-gray-500 text-sm">Track invoice status from draft to paid. Dashboard stats, client history, and overdue alerts at a glance.</p>
      </div>
      <!-- Card 4 -->
      <div class="p-6 rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition">
        <div class="w-12 h-12 flex items-center justify-center rounded-lg bg-purple-50 text-purple-500 mb-4">
          <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
        </div>
        <h3 class="font-semibold text-lg mb-2">Email Open Tracking</h3>
        <p class="text-gray-500 text-sm">Know exactly when clients open your invoices and reminders with invisible tracking pixel integration.</p>
      </div>
    </div>
  </div>
</section>

<!-- Pricing -->
<section id="pricing" class="py-20 bg-gray-50">
  <div class="max-w-5xl mx-auto px-6">
    <h2 class="text-3xl font-bold text-center mb-4">Simple, Transparent Pricing</h2>
    <p class="text-center text-gray-500 mb-14">Start free. Scale when you need to.</p>
    <div class="grid md:grid-cols-3 gap-8">
      <!-- Free -->
      <div class="bg-white rounded-2xl border border-gray-200 p-8 flex flex-col">
        <h3 class="text-lg font-semibold">Free</h3>
        <div class="mt-4 mb-6"><span class="text-4xl font-extrabold">$0</span><span class="text-gray-500">/mo</span></div>
        <ul class="space-y-3 text-sm text-gray-600 flex-1">
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>10 invoices / month</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Basic PDF templates</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Community support</li>
        </ul>
        <a href="#api" class="mt-8 block text-center py-2.5 rounded-lg border border-gray-300 font-semibold hover:border-sky-400 hover:text-sky-600 transition">Get Started</a>
      </div>
      <!-- Pro -->
      <div class="bg-white rounded-2xl border-2 border-sky-500 p-8 flex flex-col relative shadow-lg">
        <span class="absolute -top-3 left-1/2 -translate-x-1/2 bg-sky-500 text-white text-xs font-bold px-3 py-1 rounded-full">POPULAR</span>
        <h3 class="text-lg font-semibold">Pro</h3>
        <div class="mt-4 mb-6"><span class="text-4xl font-extrabold">$18</span><span class="text-gray-500">/mo</span></div>
        <ul class="space-y-3 text-sm text-gray-600 flex-1">
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Unlimited invoices</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Custom branding &amp; logo</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Auto-chase reminders</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Priority support</li>
        </ul>
        <a href="#api" class="mt-8 block text-center py-2.5 rounded-lg bg-sky-500 text-white font-semibold shadow hover:bg-sky-600 transition">Start Free Trial</a>
      </div>
      <!-- Enterprise -->
      <div class="bg-white rounded-2xl border border-gray-200 p-8 flex flex-col">
        <h3 class="text-lg font-semibold">Enterprise</h3>
        <div class="mt-4 mb-6"><span class="text-4xl font-extrabold">Custom</span></div>
        <ul class="space-y-3 text-sm text-gray-600 flex-1">
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Stripe Connect integration</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>Custom payment flows</li>
          <li class="flex items-start gap-2"><svg class="w-5 h-5 text-sky-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>SLA &amp; dedicated support</li>
        </ul>
        <a href="mailto:hello@rjctdlabs.xyz" class="mt-8 block text-center py-2.5 rounded-lg border border-gray-300 font-semibold hover:border-sky-400 hover:text-sky-600 transition">Contact Us</a>
      </div>
    </div>
  </div>
</section>

<!-- API Reference -->
<section id="api" class="py-20">
  <div class="max-w-4xl mx-auto px-6">
    <h2 class="text-3xl font-bold text-center mb-4">API Reference</h2>
    <p class="text-center text-gray-500 mb-12">RESTful JSON API. All endpoints accept and return <code class="text-sm bg-gray-100 px-1.5 py-0.5 rounded">application/json</code>.</p>
    <div class="space-y-6">
      <div class="bg-white border border-gray-200 rounded-xl p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="px-2.5 py-0.5 text-xs font-bold bg-green-100 text-green-700 rounded">POST</span>
          <code class="font-mono text-sm">/invoices</code>
        </div>
        <p class="text-gray-500 text-sm">Create a new invoice. Accepts <code class="bg-gray-100 px-1 rounded">client_name</code>, <code class="bg-gray-100 px-1 rounded">client_email</code>, <code class="bg-gray-100 px-1 rounded">items[]</code>, <code class="bg-gray-100 px-1 rounded">due_date</code>, optional <code class="bg-gray-100 px-1 rounded">tax_rate</code>, <code class="bg-gray-100 px-1 rounded">currency</code>, <code class="bg-gray-100 px-1 rounded">notes</code>, <code class="bg-gray-100 px-1 rounded">late_fee_percent</code>. Returns the created invoice with totals.</p>
      </div>
      <div class="bg-white border border-gray-200 rounded-xl p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="px-2.5 py-0.5 text-xs font-bold bg-green-100 text-green-700 rounded">POST</span>
          <code class="font-mono text-sm">/invoices/{id}/send</code>
        </div>
        <p class="text-gray-500 text-sm">Email the invoice to the client with a PDF attachment. Updates status to <code class="bg-gray-100 px-1 rounded">sent</code>. Requires SMTP configuration via environment variables.</p>
      </div>
      <div class="bg-white border border-gray-200 rounded-xl p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="px-2.5 py-0.5 text-xs font-bold bg-blue-100 text-blue-700 rounded">GET</span>
          <code class="font-mono text-sm">/invoices/{id}/pdf</code>
        </div>
        <p class="text-gray-500 text-sm">Download the invoice as a PDF file. Includes line items, totals, tax, late fees, and company branding.</p>
      </div>
      <div class="bg-white border border-gray-200 rounded-xl p-6">
        <div class="flex items-center gap-3 mb-2">
          <span class="px-2.5 py-0.5 text-xs font-bold bg-green-100 text-green-700 rounded">POST</span>
          <code class="font-mono text-sm">/invoices/{id}/remind</code>
        </div>
        <p class="text-gray-500 text-sm">Manually trigger a reminder for an overdue invoice. The tone escalates automatically: friendly, firm, urgent, then final notice based on reminder count.</p>
      </div>
    </div>
    <p class="text-center text-sm text-gray-400 mt-8">Full OpenAPI spec available at <a href="/docs" class="text-sky-500 hover:underline">/docs</a></p>
  </div>
</section>

<!-- Footer -->
<footer class="border-t border-gray-100 py-12 bg-white">
  <div class="max-w-6xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-6 text-sm text-gray-500">
    <div class="flex items-center gap-2">
      <svg class="w-5 h-5 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
      <span class="font-semibold text-gray-700">InvoicePilot</span>
    </div>
    <div class="flex items-center gap-6">
      <a href="https://github.com/therealMrFunGuy/invoice-pilot" target="_blank" class="hover:text-sky-600 transition">GitHub</a>
      <a href="https://pypi.org/project/mcp-server-invoicepilot/" target="_blank" class="hover:text-sky-600 transition">PyPI</a>
      <a href="/docs" class="hover:text-sky-600 transition">API Docs</a>
    </div>
    <div>Powered by <a href="https://rjctdlabs.xyz" class="text-sky-500 hover:underline">rjctdlabs.xyz</a></div>
  </div>
</footer>

</body>
</html>
"""


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
