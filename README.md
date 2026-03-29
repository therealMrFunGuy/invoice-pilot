# InvoicePilot

Smart invoicing service with auto-chase payment reminders. Create professional invoices, send them via email with PDF attachments, and automatically follow up on overdue payments with escalating reminders.

## Features

- **Invoice Management**: Full CRUD for invoices with line items, tax, and late fees
- **PDF Generation**: Professional invoice PDFs with reportlab
- **Auto-Chase Reminders**: Escalating reminder sequence (friendly -> firm -> late fee -> final notice)
- **Email Notifications**: SMTP-based email with HTML templates and PDF attachments
- **Client Payment Page**: One-click payment page for each invoice
- **Email Open Tracking**: Tracking pixel in reminder emails
- **MCP Server**: AI assistant integration via Model Context Protocol
- **Free Tier**: 5 invoices/month limit (configurable)

## Quick Start

```bash
# Docker
docker compose up -d

# Or run directly
pip install -r requirements.txt
python server.py
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /invoices | Create invoice |
| GET | /invoices | List invoices |
| GET | /invoices/{id} | Get invoice |
| PUT | /invoices/{id} | Update invoice |
| DELETE | /invoices/{id} | Delete invoice |
| POST | /invoices/{id}/send | Send invoice email |
| POST | /invoices/{id}/mark-paid | Mark as paid |
| POST | /invoices/{id}/remind | Send reminder |
| GET | /invoices/{id}/pdf | Download PDF |
| GET | /invoices/{id}/pay | Client payment page |
| GET | /dashboard | Revenue summary |
| GET | /clients | Client list |

## MCP Tools

- `create_invoice` - Create and optionally send an invoice
- `list_invoices` - Show all invoices with status
- `get_outstanding` - Show unpaid invoices
- `send_reminder` - Trigger reminder for overdue invoice
- `mark_paid` - Mark invoice as paid
- `get_revenue_summary` - Revenue and outstanding totals

## Reminder Escalation

| Days Overdue | Level | Action |
|-------------|-------|--------|
| 1 | Friendly | Polite payment reminder |
| 7 | Firm | Stronger reminder |
| 14 | Late Fee | Apply late fee + notice |
| 30 | Final | Final warning before escalation |

## Configuration

Copy `.env.example` to `.env` and configure SMTP settings for email delivery.
