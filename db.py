"""Postgres data access layer for the Vercel deployment of EasyTax-OCR.

Unlike the local (SQLite) version, this one:
  - Talks to a hosted Postgres instance (Neon, Supabase, or any Postgres
    with a standard connection string) via DATABASE_URL.
  - Stores the original uploaded file as bytea directly in the invoices
    row instead of on local disk, because Vercel serverless functions
    have no persistent filesystem.

Set the DATABASE_URL environment variable, e.g.:
  postgresql://user:password@host/dbname?sslmode=require

Every row carries a user_id (the Supabase Auth user's UUID) so each account
only ever sees its own clients, invoices and activity.
"""
import os
import json
import datetime
import psycopg2
import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    user_id UUID,
    name TEXT NOT NULL,
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

-- per-user data isolation (also migrates databases created before login existed)
ALTER TABLE clients ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS clients_user_name_key ON clients (user_id, name);
CREATE INDEX IF NOT EXISTS invoices_user_id_idx ON invoices (user_id);
CREATE INDEX IF NOT EXISTS activity_log_user_id_idx ON activity_log (user_id);

-- The anon key is public (the browser needs it for Supabase Auth). With RLS
-- on and no policies, Supabase's auto REST API can't read these tables;
-- this app's own connection (the table owner) is unaffected.
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log ENABLE ROW LEVEL SECURITY;
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
    conn.close()


def ensure_default_client(user_id):
    """Give a brand-new account one client to upload into."""
    conn = get_conn()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM clients WHERE user_id = %s LIMIT 1", (user_id,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO clients (user_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, "ลูกค้าทั่วไป"),
            )
    conn.close()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def log_activity(user_id, client_id, invoice_id, action, detail):
    conn = get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO activity_log (user_id, client_id, invoice_id, action, detail) VALUES (%s,%s,%s,%s,%s)",
            (user_id, client_id, invoice_id, action, detail),
        )
    conn.close()


def to_jsonb(value):
    """Wrap a Python list/dict so psycopg2 stores it as JSONB."""
    return psycopg2.extras.Json(value)
