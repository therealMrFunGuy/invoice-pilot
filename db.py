"""SQLite database layer for InvoicePilot."""

import sqlite3
import json
import os
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = os.environ.get("INVOICEPILOT_DB", "/data/invoice-pilot/invoicepilot.db")


def get_db_path():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE NOT NULL,
                client_name TEXT NOT NULL,
                client_email TEXT NOT NULL,
                items_json TEXT NOT NULL DEFAULT '[]',
                subtotal REAL NOT NULL DEFAULT 0,
                tax_rate REAL NOT NULL DEFAULT 0,
                tax REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                payment_link TEXT,
                notes TEXT,
                late_fee_percent REAL DEFAULT 0,
                late_fee_applied REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT,
                paid_at TEXT
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                level INTEGER NOT NULL,
                level_name TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                opened_at TEXT,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
            CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date);
            CREATE INDEX IF NOT EXISTS idx_invoices_client_email ON invoices(client_email);
            CREATE INDEX IF NOT EXISTS idx_reminders_invoice_id ON reminders(invoice_id);
        """)

        # Seed default settings
        defaults = {
            "late_fee_percent": "2.0",
            "late_fee_grace_days": "3",
            "company_name": "InvoicePilot",
            "company_email": "",
            "company_address": "",
            "free_tier_limit": "5",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )


def next_invoice_number() -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT invoice_number FROM invoices ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return "INV-0001"
        num = int(row["invoice_number"].split("-")[1]) + 1
        return f"INV-{num:04d}"


def create_invoice(data: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    inv_num = next_invoice_number()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO invoices
            (invoice_number, client_name, client_email, items_json,
             subtotal, tax_rate, tax, total, currency, due_date,
             status, payment_link, notes, late_fee_percent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)""",
            (
                inv_num,
                data["client_name"],
                data["client_email"],
                json.dumps(data.get("items", [])),
                data.get("subtotal", 0),
                data.get("tax_rate", 0),
                data.get("tax", 0),
                data.get("total", 0),
                data.get("currency", "USD"),
                data["due_date"],
                data.get("payment_link"),
                data.get("notes"),
                data.get("late_fee_percent", 0),
                now,
                now,
            ),
        )
        invoice_id = cur.lastrowid
    return get_invoice(invoice_id)


def get_invoice(invoice_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if row is None:
            return None
        inv = dict(row)
        inv["items"] = json.loads(inv.pop("items_json"))
        # Attach reminders
        reminders = conn.execute(
            "SELECT * FROM reminders WHERE invoice_id = ? ORDER BY sent_at",
            (invoice_id,),
        ).fetchall()
        inv["reminders"] = [dict(r) for r in reminders]
        return inv


def list_invoices(status: str | None = None, client_email: str | None = None) -> list:
    with get_conn() as conn:
        query = "SELECT * FROM invoices WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if client_email:
            query += " AND client_email = ?"
            params.append(client_email)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            inv = dict(row)
            inv["items"] = json.loads(inv.pop("items_json"))
            results.append(inv)
        return results


def update_invoice(invoice_id: int, data: dict) -> dict | None:
    existing = get_invoice(invoice_id)
    if existing is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    allowed = [
        "client_name", "client_email", "due_date", "currency",
        "payment_link", "notes", "tax_rate", "late_fee_percent",
        "status", "items", "subtotal", "tax", "total",
        "sent_at", "paid_at", "late_fee_applied",
    ]
    sets = ["updated_at = ?"]
    params = [now]
    for key in allowed:
        if key in data:
            col = "items_json" if key == "items" else key
            val = json.dumps(data[key]) if key == "items" else data[key]
            sets.append(f"{col} = ?")
            params.append(val)
    params.append(invoice_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE invoices SET {', '.join(sets)} WHERE id = ?", params
        )
    return get_invoice(invoice_id)


def delete_invoice(invoice_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        return cur.rowcount > 0


def add_reminder(invoice_id: int, level: int, level_name: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (invoice_id, level, level_name, sent_at) VALUES (?, ?, ?, ?)",
            (invoice_id, level, level_name, now),
        )
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def mark_reminder_opened(reminder_id: int):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET opened_at = ? WHERE id = ?", (now, reminder_id)
        )


def get_last_reminder(invoice_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE invoice_id = ? ORDER BY level DESC LIMIT 1",
            (invoice_id,),
        ).fetchone()
        return dict(row) if row else None


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )


def get_unique_clients() -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT client_name, client_email,
                   COUNT(*) as invoice_count,
                   SUM(CASE WHEN status IN ('sent', 'overdue') THEN total ELSE 0 END) as outstanding,
                   SUM(CASE WHEN status = 'paid' THEN total ELSE 0 END) as paid_total,
                   MAX(created_at) as last_invoice
            FROM invoices
            GROUP BY client_email
            ORDER BY last_invoice DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_dashboard_stats() -> dict:
    with get_conn() as conn:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        outstanding = conn.execute(
            "SELECT COALESCE(SUM(total), 0) as amt, COUNT(*) as cnt FROM invoices WHERE status IN ('sent', 'overdue')"
        ).fetchone()
        overdue = conn.execute(
            "SELECT COALESCE(SUM(total), 0) as amt, COUNT(*) as cnt FROM invoices WHERE status = 'overdue'"
        ).fetchone()
        paid_month = conn.execute(
            "SELECT COALESCE(SUM(total), 0) as amt, COUNT(*) as cnt FROM invoices WHERE status = 'paid' AND paid_at >= ?",
            (month_start,),
        ).fetchone()
        total_rev = conn.execute(
            "SELECT COALESCE(SUM(total), 0) as amt, COUNT(*) as cnt FROM invoices WHERE status = 'paid'"
        ).fetchone()
        invoice_count = conn.execute("SELECT COUNT(*) as cnt FROM invoices").fetchone()
        month_created = conn.execute(
            "SELECT COUNT(*) as cnt FROM invoices WHERE created_at >= ?",
            (month_start,),
        ).fetchone()

        return {
            "outstanding": {"amount": outstanding["amt"], "count": outstanding["cnt"]},
            "overdue": {"amount": overdue["amt"], "count": overdue["cnt"]},
            "paid_this_month": {"amount": paid_month["amt"], "count": paid_month["cnt"]},
            "total_revenue": {"amount": total_rev["amt"], "count": total_rev["cnt"]},
            "total_invoices": invoice_count["cnt"],
            "invoices_this_month": month_created["cnt"],
        }


def get_invoices_this_month_count() -> int:
    with get_conn() as conn:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM invoices WHERE created_at >= ?",
            (month_start,),
        ).fetchone()
        return row["cnt"]
