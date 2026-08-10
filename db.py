"""Postgres data access layer for the Vercel deployment of EasyTax-OCR.

Unlike the local (SQLite) version, this one:
  - Talks to a hosted Postgres instance (Neon, Supabase, or any Postgres
    with a standard connection string) via DATABASE_URL.
  - Stores the original uploaded file as bytea directly in the invoices
    row instead of on local disk, because Vercel serverless functions
    have no persistent filesystem.

Set the DATABASE_URL environment variable, e.g.:
  postgresql://user:password@host/dbname?sslmode=require
"""
import os
import json
import datetime
import psycopg2
import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    filename TEXT,
    doc_type TEXT,
    invoice_no TEXT,
    invoice_date TEXT,
    invoice_date_raw TEXT,
    seller_name TEXT,
    seller_tax_id TEXT,
    buyer_name TEXT,
    subtotal DOUBLE PRECISION,
    vat DOUBLE PRECISION,
    total DOUBLE PRECISION,
    needs_review BOOLEAN NOT NULL DEFAULT false,
    review_reason TEXT,
    ocr_confidence DOUBLE PRECISION,
    raw_text TEXT,
    file_data BYTEA,
    file_mime TEXT,
    line_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    client_id INTEGER,
    invoice_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def get_conn():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it in Vercel project settings "
            "(Settings -> Environment Variables) pointing at your Neon/Supabase Postgres instance."
        )
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("SELECT COUNT(*) AS c FROM clients")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT INTO clients (name) VALUES (%s)", ("ลูกค้าทั่วไป",)
            )
    conn.close()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def log_activity(client_id, invoice_id, action, detail):
    conn = get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO activity_log (client_id, invoice_id, action, detail) VALUES (%s,%s,%s,%s)",
            (client_id, invoice_id, action, detail),
        )
    conn.close()


def to_jsonb(value):
    """Wrap a Python list/dict so psycopg2 stores it as JSONB."""
    return psycopg2.extras.Json(value)
