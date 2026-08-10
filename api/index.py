"""EasyTax-OCR — Vercel deployment entry point.

This is a Flask app (Vercel's Python runtime auto-detects the `app` WSGI
object in api/index.py and routes every request to it — see vercel.json).

Differences from the local/Tesseract version:
  - Storage is Postgres (via db.py) instead of SQLite, because Vercel
    functions have no persistent disk.
  - OCR is Google Cloud Vision (via ocr_engine.py) instead of Tesseract,
    because Vercel functions can't run system binaries.
  - Uploaded files are stored as bytea in the invoices row and served back
    from the same route (/api/invoices/<id>/file) instead of a local
    uploads/ folder.
  - extractor.py (field extraction / classification / review-flagging)
    is untouched — it only depends on plain OCR text, not the engine.
"""
import os
import io
import csv
import json
import datetime
import sys

import psycopg2
from flask import Flask, request, jsonify, Response, send_file

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db
import extractor
import ocr_engine

app = Flask(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")

_db_ready = False


def ensure_db():
    global _db_ready
    if not _db_ready:
        db.init_db()
        _db_ready = True


def month_key(iso_date):
    if not iso_date:
        return None
    try:
        d = datetime.date.fromisoformat(iso_date)
        return f"{d.year:04d}-{d.month:02d}"
    except ValueError:
        return None


def invoice_row_to_dict(row, include_file_flag=True):
    d = dict(row)
    file_data = d.pop("file_data", None)
    if include_file_flag:
        d["file_url"] = f"/api/invoices/{d['id']}/file" if file_data or d.get("file_mime") else None
    if isinstance(d.get("created_at"), (datetime.datetime, datetime.date)):
        d["created_at"] = d["created_at"].isoformat()
    if d.get("line_items") is None:
        d["line_items"] = []
    return d


# ---------------------------------------------------------------- static --
@app.route("/")
def index():
    ensure_db()
    path = os.path.join(STATIC_DIR, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


# --------------------------------------------------------------- clients --
@app.route("/api/clients", methods=["GET"])
def list_clients():
    ensure_db()
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM clients ORDER BY name")
        rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("created_at"), (datetime.datetime, datetime.date)):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return jsonify(out)


@app.route("/api/clients", methods=["POST"])
def create_client():
    ensure_db()
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO clients (name) VALUES (%s) RETURNING id", (name,))
            client_id = cur.fetchone()["id"]
    except Exception as e:
        conn.close()
        return jsonify({"error": f"ไม่สามารถสร้างลูกค้าได้: {e}"}), 400
    conn.close()
    return jsonify({"id": client_id, "name": name}), 201


# -------------------------------------------------------------- dashboard --
@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    ensure_db()
    client_id = request.args.get("client_id", "all")
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cols = "id, client_id, doc_type, vat, total, invoice_date, invoice_no, seller_name, needs_review, created_at"
        if client_id != "all":
            cur.execute(f"SELECT {cols} FROM invoices WHERE client_id = %s", (int(client_id),))
        else:
            cur.execute(f"SELECT {cols} FROM invoices")
        rows = cur.fetchall()
    conn.close()

    count = len(rows)
    vat_deductible = sum(float(r["vat"] or 0) for r in rows if r["doc_type"] == "เต็มรูป")
    vat_non_deductible_count = sum(1 for r in rows if r["doc_type"] == "ย่อ")
    total_all = sum(float(r["total"] or 0) for r in rows)
    needs_review = sum(1 for r in rows if r["needs_review"])

    monthly = {}
    for r in rows:
        mk = month_key(r["invoice_date"])
        if not mk:
            continue
        monthly.setdefault(mk, {"vat": 0.0, "total": 0.0})
        monthly[mk]["vat"] += float(r["vat"] or 0)
        monthly[mk]["total"] += float(r["total"] or 0)
    months_sorted = sorted(monthly.keys())[-12:]
    series = [{"month": m, "vat": monthly[m]["vat"], "total": monthly[m]["total"]} for m in months_sorted]

    recent = sorted(rows, key=lambda r: r["created_at"], reverse=True)[:5]
    recent_out = [{
        "id": r["id"], "seller_name": r["seller_name"], "invoice_no": r["invoice_no"],
        "invoice_date": r["invoice_date"], "total": r["total"], "needs_review": bool(r["needs_review"]),
        "doc_type": r["doc_type"],
    } for r in recent]

    return jsonify({
        "count": count,
        "vat_deductible": round(vat_deductible, 2),
        "vat_non_deductible_count": vat_non_deductible_count,
        "total_all": round(total_all, 2),
        "needs_review": needs_review,
        "monthly_series": series,
        "recent": recent_out,
    })


# -------------------------------------------------------------- invoices --
@app.route("/api/invoices", methods=["GET"])
def list_invoices():
    ensure_db()
    client_id = request.args.get("client_id", "all")
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()

    where = []
    params = []
    if client_id != "all":
        where.append("client_id = %s")
        params.append(int(client_id))
    if status == "needs_review":
        where.append("needs_review = true")
    if q:
        where.append("(seller_name ILIKE %s OR invoice_no ILIKE %s OR invoice_date ILIKE %s OR seller_tax_id ILIKE %s)")
        like = f"%{q}%"
        params += [like, like, like, like]
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cols = ("id, client_id, filename, doc_type, invoice_no, invoice_date, invoice_date_raw, "
            "seller_name, seller_tax_id, buyer_name, subtotal, vat, total, needs_review, "
            "review_reason, ocr_confidence, file_mime, line_items, created_at")
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM invoices {where_sql} ORDER BY created_at DESC", params)
        rows = cur.fetchall()
    conn.close()
    return jsonify([invoice_row_to_dict(r) for r in rows])


@app.route("/api/invoices/<int:invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    ensure_db()
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, client_id, filename, doc_type, invoice_no, invoice_date, invoice_date_raw, "
            "seller_name, seller_tax_id, buyer_name, subtotal, vat, total, needs_review, review_reason, "
            "ocr_confidence, file_mime, line_items, created_at FROM invoices WHERE id = %s",
            (invoice_id,),
        )
        row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(invoice_row_to_dict(row))


@app.route("/api/invoices/<int:invoice_id>/file", methods=["GET"])
def get_invoice_file(invoice_id):
    ensure_db()
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT file_data, file_mime, filename FROM invoices WHERE id = %s", (invoice_id,))
        row = cur.fetchone()
    conn.close()
    if not row or not row["file_data"]:
        return jsonify({"error": "no original file for this invoice"}), 404
    return send_file(
        io.BytesIO(bytes(row["file_data"])),
        mimetype=row["file_mime"] or "application/octet-stream",
        download_name=row["filename"] or f"invoice_{invoice_id}",
    )


@app.route("/api/invoices/<int:invoice_id>", methods=["PUT"])
def update_invoice(invoice_id):
    ensure_db()
    payload = request.get_json(silent=True) or {}
    allowed = [
        "doc_type", "invoice_no", "invoice_date", "seller_name", "seller_tax_id",
        "buyer_name", "subtotal", "vat", "total", "needs_review", "review_reason",
    ]
    fields = {k: v for k, v in payload.items() if k in allowed}
    if "line_items" in payload:
        fields["line_items"] = db.to_jsonb(payload["line_items"])
    if not fields:
        return jsonify({"error": "no editable fields provided"}), 400

    set_sql = ", ".join(f"{k} = %s" for k in fields)
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(f"UPDATE invoices SET {set_sql} WHERE id = %s", list(fields.values()) + [invoice_id])
        cur.execute(
            "SELECT id, client_id, filename, doc_type, invoice_no, invoice_date, invoice_date_raw, "
            "seller_name, seller_tax_id, buyer_name, subtotal, vat, total, needs_review, review_reason, "
            "ocr_confidence, file_mime, line_items, created_at FROM invoices WHERE id = %s",
            (invoice_id,),
        )
        row = cur.fetchone()
    conn.close()
    if row:
        db.log_activity(row["client_id"], invoice_id, "edit", json.dumps(list(fields.keys()), ensure_ascii=False))
    return jsonify(invoice_row_to_dict(row) if row else {})


@app.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
def delete_invoice(invoice_id):
    ensure_db()
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT client_id, filename FROM invoices WHERE id = %s", (invoice_id,))
        row = cur.fetchone()
        cur.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
    conn.close()
    if row:
        db.log_activity(row["client_id"], invoice_id, "delete", row["filename"])
    return jsonify({"deleted": invoice_id})


# ---------------------------------------------------------------- upload --
@app.route("/api/upload", methods=["POST"])
def upload():
    ensure_db()
    client_id = request.form.get("client_id")
    if not client_id:
        return jsonify({"error": "client_id is required"}), 400
    client_id = int(client_id)

    files = request.files.getlist("files")
    results = []
    conn = db.get_conn()
    for f in files:
        if not f or not f.filename:
            continue
        filename = f.filename
        file_bytes = f.read()
        mime = f.mimetype or "application/octet-stream"

        try:
            pages = ocr_engine.process_upload(filename, file_bytes)
        except Exception as e:
            results.append({"filename": filename, "status": "error", "message": str(e)})
            continue

        saved_count = 0
        with conn, conn.cursor() as cur:
            for page in pages:
                chunks = extractor.split_multi_invoice_text(page["text"])
                for i, chunk in enumerate(chunks):
                    fields = extractor.extract_fields(chunk, ocr_confidence=page["confidence"])
                    # only attach the original file bytes to the first record
                    # created from this upload, to avoid storing duplicate
                    # blobs for every split invoice on a multi-invoice page
                    file_data = file_bytes if (page["source_page"] == 1 and i == 0) else None
                    cur.execute(
                        """INSERT INTO invoices
                        (client_id, filename, doc_type, invoice_no, invoice_date, invoice_date_raw,
                         seller_name, seller_tax_id, buyer_name, subtotal, vat, total,
                         needs_review, review_reason, ocr_confidence, raw_text, file_data, file_mime,
                         line_items)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            client_id, filename, fields["doc_type"], fields["invoice_no"],
                            fields["invoice_date_iso"], fields["invoice_date_raw"],
                            fields["seller_name"], fields["seller_tax_id"], fields["buyer_name"],
                            fields["subtotal"], fields["vat"], fields["total"],
                            fields["needs_review"], fields["review_reason"],
                            fields["ocr_confidence"], chunk,
                            psycopg2.Binary(file_data) if file_data else None,
                            mime if file_data else None,
                            db.to_jsonb(fields["line_items"]),
                        ),
                    )
                    saved_count += 1
        results.append({"filename": filename, "status": "ok", "invoices_created": saved_count, "pages": len(pages)})

    conn.close()
    db.log_activity(client_id, None, "upload", json.dumps(results, ensure_ascii=False))
    return jsonify({"results": results})


# ---------------------------------------------------------------- activity --
@app.route("/api/activity", methods=["GET"])
def activity():
    ensure_db()
    client_id = request.args.get("client_id", "all")
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        if client_id != "all":
            cur.execute(
                "SELECT * FROM activity_log WHERE client_id = %s ORDER BY created_at DESC LIMIT 200",
                (int(client_id),),
            )
        else:
            cur.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 200")
        rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("created_at"), (datetime.datetime, datetime.date)):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return jsonify(out)


# ------------------------------------------------------------------ export --
@app.route("/api/export.csv", methods=["GET"])
def export_csv():
    ensure_db()
    client_id = request.args.get("client_id", "all")
    scope = request.args.get("scope", "all")

    where = []
    params = []
    if client_id != "all":
        where.append("client_id = %s")
        params.append(int(client_id))
    if scope == "month":
        today = datetime.date.today()
        mk = f"{today.year:04d}-{today.month:02d}"
        where.append("invoice_date LIKE %s")
        params.append(f"{mk}%")
    elif scope == "full_only":
        where.append("doc_type = 'เต็มรูป'")
    elif scope == "review":
        where.append("needs_review = true")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    fieldnames = [
        "id", "filename", "doc_type", "seller_name", "seller_tax_id", "buyer_name",
        "invoice_no", "invoice_date", "subtotal", "vat", "total", "needs_review", "review_reason",
    ]
    conn = db.get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(fieldnames)} FROM invoices {where_sql} ORDER BY invoice_date", params
        )
        rows = cur.fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))
    body = "﻿" + buf.getvalue()  # BOM so Excel shows Thai correctly

    db.log_activity(None if client_id == "all" else int(client_id), None, "export", scope)
    return Response(
        body, mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="easytax_export_{scope}.csv"'},
    )


# Vercel's Python runtime looks for a WSGI-compatible `app` object in this
# file — nothing else to do here (no app.run()).
