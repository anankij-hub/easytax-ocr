# -*- coding: utf-8 -*-
"""อ่านใบกำกับทั้งไฟล์ PDF เป็นชุด แล้วสรุปว่าระบบอ่านได้แค่ไหน

    python batch_ocr.py "ใบจริงอันใหม่.pdf"
    python batch_ocr.py "ใบจริงอันใหม่.pdf" --pages 1-10
    python batch_ocr.py "ใบจริงอันใหม่.pdf" --rescore

สิ่งที่ได้:
  batch_out/raw/page_001.txt   ข้อความดิบจาก OCR (เก็บไว้ใช้ซ้ำ)
  batch_out/page_001.txt       ข้อความดิบ + ฟิลด์ที่แยกได้
  batch_out/summary.txt        ตารางสรุปทุกหน้า

ข้อความดิบถูก cache ไว้ — รันซ้ำจะไม่เรียก Cloud Vision ใหม่ ไม่เสียเงินเพิ่ม
ใช้ --rescore เมื่อแก้ extractor.py แล้วอยากดูผลใหม่จากข้อความเดิม
"""
import io
import os
import sys

# reconfigure ไม่ใช่สร้าง TextIOWrapper ใหม่ทับ — การทับทำให้ stdout เดิมถูกปิด
# เมื่อไฟล์นี้ถูก import เข้าไปในสคริปต์อื่น
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extractor

OUT_DIR = "batch_out"
RAW_DIR = os.path.join(OUT_DIR, "raw")
RENDER_DPI = 200

FIELD_KEYS = ("doc_type", "invoice_no", "invoice_date_iso", "seller_name",
              "seller_tax_id", "buyer_name", "subtotal", "vat", "total")


def parse_pages(spec, total):
    """"1-10" หรือ "3,7,12" หรือ "5" -> เซ็ตของเลขหน้า (เริ่มที่ 1)"""
    if not spec:
        return set(range(1, total + 1))
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return {p for p in out if 1 <= p <= total}


def render_pages(pdf_path, wanted):
    """แปลงหน้า PDF เป็น PNG. ใช้ PyMuPDF ซึ่งติดตั้งไว้แล้ว"""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            print("ต้องติดตั้ง PyMuPDF ก่อน:  pip install PyMuPDF")
            sys.exit(1)
    doc = pymupdf.open(pdf_path)
    zoom = RENDER_DPI / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    try:
        for index, page in enumerate(doc):
            number = index + 1
            if number in wanted:
                yield number, page.get_pixmap(matrix=matrix).tobytes("png")
    finally:
        doc.close()


def page_count(pdf_path):
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    doc = pymupdf.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()


def ocr_page(number, png_bytes):
    """ข้อความดิบของหน้านี้ — จาก cache ถ้ามี ไม่งั้นเรียก Cloud Vision"""
    cache = os.path.join(RAW_DIR, f"page_{number:03d}.txt")
    if os.path.exists(cache):
        with io.open(cache, encoding="utf-8") as fh:
            return fh.read(), True
    import ocr_engine
    text, _conf = ocr_engine.ocr_image_bytes(png_bytes)
    with io.open(cache, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text, False


def score(fields):
    """แยกฟิลด์ได้กี่ช่อง และยอดสอดคล้องกันไหม"""
    filled = sum(1 for k in FIELD_KEYS if fields[k] not in (None, ""))
    amounts_ok = extractor.totals_mismatch_reason(
        fields["subtotal"], fields["vat"], fields["total"]
    ) is None and fields["total"] is not None
    return filled, amounts_ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    pdf_path = args[0]
    if not os.path.exists(pdf_path):
        print(f"หาไฟล์ไม่เจอ: {pdf_path}")
        here = os.path.dirname(os.path.abspath(__file__))
        found = sorted(f for f in os.listdir(here) if f.lower().endswith(".pdf"))
        if found:
            print("\nไฟล์ PDF ที่อยู่ในโฟลเดอร์นี้:")
            for name in found:
                print(f'   python batch_ocr.py "{name}"')
        else:
            print("\nโฟลเดอร์นี้ไม่มีไฟล์ PDF เลย — ก๊อปไฟล์มาวางที่")
            print(f"   {here}")
            print("หรือใส่ที่อยู่เต็มของไฟล์ เช่น")
            print('   python batch_ocr.py "C:\\Users\\ADMIN\\Downloads\\ใบจริงอันใหม่.pdf"')
        return 1

    spec = None
    for a in sys.argv[1:]:
        if a.startswith("--pages="):
            spec = a.split("=", 1)[1]
    if "--pages" in sys.argv:
        i = sys.argv.index("--pages")
        if i + 1 < len(sys.argv):
            spec = sys.argv[i + 1]
    rescore_only = "--rescore" in sys.argv

    # ตรวจ API key ก่อนเริ่ม ดีกว่าปล่อยให้พังตอนยิงหน้าแรก
    if not rescore_only:
        key = os.environ.get("GOOGLE_VISION_API_KEY", "")
        if not key:
            print("ยังไม่ได้ตั้ง GOOGLE_VISION_API_KEY")
            print('  setx GOOGLE_VISION_API_KEY "AIza..."   แล้วปิด cmd เปิดใหม่')
            return 1
        if not key.isascii() or len(key) < 20:
            print("ค่า GOOGLE_VISION_API_KEY ดูไม่เหมือนคีย์จริง:")
            print(f"  ที่ตั้งไว้ตอนนี้: {key!r}")
            print()
            print("คีย์ของ Google เป็นตัวอักษรอังกฤษล้วน ยาวราว 39 ตัว ขึ้นต้นด้วย AIza")
            print("ไปก๊อปค่าจริงจาก Vercel -> Settings -> Environment Variables")
            print('แล้วสั่ง  setx GOOGLE_VISION_API_KEY "AIza..."  และปิด cmd เปิดใหม่')
            return 1

    os.makedirs(RAW_DIR, exist_ok=True)
    total = page_count(pdf_path)
    wanted = parse_pages(spec, total)
    print(f"ไฟล์ {pdf_path} มี {total} หน้า — จะประมวลผล {len(wanted)} หน้า")

    if rescore_only:
        # ไม่เรียก OCR เลย ใช้ข้อความที่ cache ไว้
        pages = []
        for number in sorted(wanted):
            cache = os.path.join(RAW_DIR, f"page_{number:03d}.txt")
            if os.path.exists(cache):
                with io.open(cache, encoding="utf-8") as fh:
                    pages.append((number, fh.read(), True))
        if not pages:
            print("ยังไม่มีข้อความที่ cache ไว้ — รันโดยไม่ใส่ --rescore ก่อน")
            return 1
    else:
        pages = []
        for number, png in render_pages(pdf_path, wanted):
            try:
                text, cached = ocr_page(number, png)
            except Exception as e:
                print(f"  หน้า {number}: อ่านไม่สำเร็จ — {e}")
                if "GOOGLE_VISION_API_KEY" in str(e):
                    return 1
                continue
            pages.append((number, text, cached))
            mark = "cache" if cached else "OCR  "
            print(f"  [{mark}] หน้า {number}/{total}")

    rows = []
    for number, text, _cached in pages:
        fields = extractor.extract_fields(text, ocr_confidence=None)
        filled, amounts_ok = score(fields)
        rows.append((number, fields, filled, amounts_ok))

        out = [f"=== หน้า {number} ===", ""]
        out.append("--- ฟิลด์ที่แยกได้ ---")
        for key in FIELD_KEYS:
            out.append(f"{key:18} = {fields[key]}")
        out.append(f"{'needs_review':18} = {fields['needs_review']}")
        if fields["review_reason"]:
            out.append(f"{'review_reason':18} = {fields['review_reason']}")
        out += ["", "--- ข้อความดิบ ---", text, ""]
        with io.open(os.path.join(OUT_DIR, f"page_{number:03d}.txt"),
                     "w", encoding="utf-8") as fh:
            fh.write("\n".join(out))

    # ---- สรุป ----
    lines = []
    lines.append(f"ไฟล์: {pdf_path}")
    lines.append(f"ประมวลผล {len(rows)} หน้า จากทั้งหมด {total} หน้า")
    lines.append("")
    lines.append(f"{'หน้า':>5} {'ประเภท':<8} {'ฟิลด์':>6} {'ยอด':<5} "
                 f"{'เลขที่':<18} {'วันที่':<11} {'ยอดรวม':>12}  ผู้ขาย")
    lines.append("-" * 110)
    clean = flagged = 0
    for number, f, filled, amounts_ok in rows:
        if not f["needs_review"]:
            clean += 1
        else:
            flagged += 1
        seller = (f["seller_name"] or "")[:28]
        total_txt = "-" if f["total"] is None else format(f["total"], ",.2f")
        lines.append(
            f"{number:>5} {f['doc_type'] or '-':<8} {filled:>3}/{len(FIELD_KEYS)} "
            f"{'OK' if amounts_ok else 'ไม่ตรง':<5} "
            f"{(f['invoice_no'] or '-'):<18} {(f['invoice_date_iso'] or '-'):<11} "
            f"{total_txt:>12}  {seller}"
        )
    lines.append("-" * 110)
    lines.append(f"ผ่านสะอาด {clean} หน้า   ต้องตรวจมือ {flagged} หน้า")
    lines.append("")
    lines.append("เหตุผลที่ต้องตรวจ (นับตามชนิด):")
    reasons = {}
    for _n, f, _fl, _ok in rows:
        for r in (f["review_reason"] or "").split(";"):
            r = r.strip()
            if r:
                key = r.split(":")[0].split("(")[0].strip()[:60]
                reasons[key] = reasons.get(key, 0) + 1
    for key, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {count:>3} หน้า  {key}")

    report = "\n".join(lines)
    with io.open(os.path.join(OUT_DIR, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print()
    print(report)
    print()
    print(f"เขียนผลไว้ใน {OUT_DIR}\\  (เปิดด้วย VS Code เพื่อดูภาษาไทยให้ครบ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
