# -*- coding: utf-8 -*-
"""อ่านใบกำกับทั้งไฟล์ PDF เป็นชุด แล้ววัดว่าอ่าน "ถูก" กี่ช่อง

    python batch_ocr.py "ใบจริงอันใหม่.pdf"
    python batch_ocr.py "ใบจริงอันใหม่.pdf" --pages 1-10
    python batch_ocr.py "ใบจริงอันใหม่.pdf" --rescore
    python batch_ocr.py "ใบจริงอันใหม่.pdf" --rescore --printed

สิ่งที่ได้:
  batch_out/raw/page_001.txt   ข้อความดิบจาก OCR (เก็บไว้ใช้ซ้ำ)
  batch_out/page_001.txt       ข้อความดิบ + ฟิลด์ที่แยกได้ + ผิดตรงไหน
  batch_out/summary.txt        ตารางสรุปทุกหน้า + คะแนนรายฟิลด์
  batch_out/wrong.txt          เฉพาะช่องที่ผิด เทียบกับเฉลย ทีละช่อง

ข้อความดิบถูก cache ไว้ — รันซ้ำจะไม่เรียก Cloud Vision ใหม่ ไม่เสียเงินเพิ่ม
ใช้ --rescore เมื่อแก้ extractor.py แล้วอยากดูผลใหม่จากข้อความเดิม
ใช้ --printed เพื่อตัดหน้าที่ยอดเป็นลายมือออก (OCR อ่านไม่ได้อยู่แล้ว)

การให้คะแนนเทียบกับ ground_truth.py ซึ่งเป็นเฉลยที่อ่านด้วยตาจากใบจริง
ช่องที่เฉลยเป็น None แปลว่าอ่านจากภาพไม่ชัดพอจะฟันธง จะไม่ถูกนับคะแนน
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

import difflib
import re

import extractor

try:
    import ground_truth
except ImportError:
    ground_truth = None

OUT_DIR = "batch_out"
RAW_DIR = os.path.join(OUT_DIR, "raw")
RENDER_DPI = 200

FIELD_KEYS = ("doc_type", "invoice_no", "invoice_date_iso", "seller_name",
              "seller_tax_id", "buyer_name", "subtotal", "vat", "total")

# ชื่อฟิลด์ในเฉลย -> ชื่อฟิลด์ที่ extractor คืนมา
TRUTH_TO_FIELD = {
    "no": "invoice_no",
    "date": "invoice_date_iso",
    "seller": "seller_name",
    "tax_id": "seller_tax_id",
    "buyer": "buyer_name",
    "subtotal": "subtotal",
    "vat": "vat",
    "total": "total",
}
SCORED = ("doc_kind",) + tuple(TRUTH_TO_FIELD)


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


# ---------------------------------------------------------------- การให้คะแนน

# คำที่ไม่ช่วยแยกว่าเป็นบริษัทไหน — ตัดทิ้งก่อนเทียบชื่อ ไม่งั้นทุกชื่อ
# "เหมือนกัน" ตรงคำว่าบริษัท/จำกัด และ OCR ก็มักอ่านคำพวกนี้ตกหล่น
_NAME_NOISE_RE = re.compile(
    r"บริษัท|ห้างหุ้นส่วนจำกัด|ห้างหุ้นส่วน|หจก\.?|จำกัด|\(?มหาชน\)?|ร้าน|"
    r"สำนักงานใหญ่|สาขาที่|สาขา|company|limited|public|co\.?|ltd\.?|\s|[().,\-/:]"
)


def _norm_name(s):
    return _NAME_NOISE_RE.sub("", (s or "").lower())


def _name_match(expected, got):
    """ชื่อบริษัทถือว่าตรงเมื่อแกนของชื่อตรงกัน

    ไม่เทียบตรงตัวเพราะ OCR อ่าน "เอ็กซ์ตร้า/แอ็กซ์ตร้า" สลับกันได้ และใบ
    เดียวกันบางทีพิมพ์ชื่อสาขาต่อท้ายบ้างไม่ต่อบ้าง สิ่งที่ต้องการวัดคือ
    "ระบุตัวผู้ขายได้ถูกบริษัทไหม" ไม่ใช่ "สะกดตรงทุกตัวอักษรไหม"
    """
    a, b = _norm_name(expected), _norm_name(got)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    # เผื่อ OCR อ่านผิดไปไม่กี่ตัว เช่น "แอ็กซ์ตร้า" เป็น "เอ็กซ์ตร้า"
    # ซึ่งเป็นบริษัทเดียวกันแน่ ๆ แต่ตัวอักษรไม่ตรง
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _field_ok(key, expected, got):
    if key in ("subtotal", "vat", "total"):
        return got is not None and abs(float(got) - float(expected)) <= 0.01
    if key == "tax_id":
        return _digits(got) == _digits(expected)
    if key in ("seller", "buyer"):
        return _name_match(expected, got)
    if key == "no":
        return (got or "").replace(" ", "").upper() == expected.replace(" ", "").upper()
    return (got or "") == expected


def compare(truth, fields):
    """คืน (ตรวจกี่ช่อง, ถูกกี่ช่อง, รายการที่ผิด)

    ช่องที่เฉลยเป็น None ไม่ถูกนับ — ดูหัวไฟล์ ground_truth.py
    """
    checked = correct = 0
    wrong = []

    # ประเภทเอกสารนับแยก เพราะผิดที่นี่ผิดทั้งใบ: ใบเต็มรูปที่ถูกตีเป็นใบย่อ
    # จะโดนล้างยอดก่อนภาษีกับ VAT ทิ้ง และหักภาษีซื้อไม่ได้
    want_full = truth["doc_kind"] == "full"
    got_full = fields.get("doc_type") == "เต็มรูป"
    checked += 1
    if want_full == got_full:
        correct += 1
    else:
        wrong.append(("doc_kind",
                      "เต็มรูป" if want_full else f'ไม่ใช่เต็มรูป ({truth["doc_kind"]})',
                      fields.get("doc_type")))

    for tkey, fkey in TRUTH_TO_FIELD.items():
        expected = truth.get(tkey)
        if expected is None:
            continue
        checked += 1
        got = fields.get(fkey)
        if _field_ok(tkey, expected, got):
            correct += 1
        else:
            wrong.append((tkey, expected, got))
    return checked, correct, wrong


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
    printed_only = "--printed" in sys.argv

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
    if printed_only:
        if ground_truth is None:
            print("--printed ต้องใช้ ground_truth.py ซึ่งหาไม่เจอ")
            return 1
        wanted &= set(ground_truth.PRINTED)
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

    truths = ground_truth.PAGES if ground_truth else {}
    rows = []
    for number, text, _cached in pages:
        fields = extractor.extract_fields(text, ocr_confidence=None)
        truth = truths.get(number)
        checked, correct, wrong = compare(truth, fields) if truth else (0, 0, [])
        rows.append((number, fields, truth, checked, correct, wrong))

        out = [f"=== หน้า {number} ===", ""]
        if truth and truth.get("note"):
            out.append(f"หมายเหตุจากเฉลย: {truth['note']}")
            out.append("")
        out.append("--- ฟิลด์ที่แยกได้ ---")
        for key in FIELD_KEYS:
            out.append(f"{key:18} = {fields[key]}")
        out.append(f"{'needs_review':18} = {fields['needs_review']}")
        if fields["review_reason"]:
            out.append(f"{'review_reason':18} = {fields['review_reason']}")
        if truth:
            out += ["", f"--- เทียบเฉลย: ถูก {correct}/{checked} ช่อง ---"]
            for key, expected, got in wrong:
                out.append(f"  ผิด {key:10} ควรเป็น {expected!r}  แต่ได้ {got!r}")
            if not wrong:
                out.append("  ถูกทุกช่องที่ตรวจได้")
        out += ["", "--- ข้อความดิบ ---", text, ""]
        with io.open(os.path.join(OUT_DIR, f"page_{number:03d}.txt"),
                     "w", encoding="utf-8") as fh:
            fh.write("\n".join(out))

    # ---- สรุป ----
    lines = []
    lines.append(f"ไฟล์: {pdf_path}")
    lines.append(f"ประมวลผล {len(rows)} หน้า จากทั้งหมด {total} หน้า"
                 + ("  (เฉพาะหน้าที่ไม่ใช่ลายมือ)" if printed_only else ""))
    lines.append("")
    lines.append(f"{'หน้า':>5} {'ถูก':>7} {'ประเภท':<8} {'เลขที่':<20} "
                 f"{'วันที่':<11} {'ยอดรวม':>11}  ผู้ขาย")
    lines.append("-" * 112)
    perfect = flagged = 0
    checked_all = correct_all = 0
    per_field = {k: [0, 0] for k in SCORED}   # [ตรวจ, ถูก]
    for number, f, truth, checked, correct, wrong in rows:
        checked_all += checked
        correct_all += correct
        if truth:
            bad = {w[0] for w in wrong}
            for key in SCORED:
                if key == "doc_kind":
                    per_field[key][0] += 1
                elif truth.get(key) is None:
                    continue
                else:
                    per_field[key][0] += 1
                if key not in bad:
                    per_field[key][1] += 1
        if checked and correct == checked:
            perfect += 1
        if f["needs_review"]:
            flagged += 1
        seller = (f["seller_name"] or "")[:26]
        total_txt = "-" if f["total"] is None else format(f["total"], ",.2f")
        score = f"{correct}/{checked}" if checked else "-"
        lines.append(
            f"{number:>5} {score:>7} {f['doc_type'] or '-':<8} "
            f"{(f['invoice_no'] or '-'):<20} {(f['invoice_date_iso'] or '-'):<11} "
            f"{total_txt:>11}  {seller}"
        )
    lines.append("-" * 112)
    if checked_all:
        pct = 100.0 * correct_all / checked_all
        lines.append(f"รวมทุกช่อง: ถูก {correct_all}/{checked_all} ({pct:.1f}%)")
        lines.append(f"หน้าที่ถูกครบทุกช่อง: {perfect}/{len(rows)}")
    lines.append(f"ระบบขึ้นธงให้ตรวจมือ: {flagged}/{len(rows)} หน้า")
    lines.append("")
    lines.append("คะแนนรายฟิลด์ (เรียงจากแย่ไปดี — ไล่แก้จากบนลงล่าง):")
    order = sorted(per_field.items(),
                   key=lambda kv: (kv[1][1] / kv[1][0]) if kv[1][0] else 1.0)
    for key, (n, ok) in order:
        if not n:
            continue
        lines.append(f"  {key:12} {ok:>3}/{n:<3} {100.0 * ok / n:5.1f}%")

    lines.append("")
    lines.append("เหตุผลที่ระบบขอให้ตรวจ (นับตามชนิด):")
    reasons = {}
    for _n, f, _t, _c, _ok, _w in rows:
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

    # ไฟล์แยกเฉพาะช่องที่ผิด — อันนี้คือรายการงานที่เหลือ
    wrong_lines = ["ช่องที่ยังอ่านผิด เทียบกับเฉลย", ""]
    for number, _f, truth, _c, _ok, wrong in rows:
        if not wrong:
            continue
        tag = " (ลายมือ)" if truth and truth.get("handwritten") else ""
        wrong_lines.append(f"หน้า {number}{tag}")
        for key, expected, got in wrong:
            wrong_lines.append(f"    {key:10} ควรเป็น {expected!r}")
            wrong_lines.append(f"    {'':10} แต่ได้   {got!r}")
        if truth and truth.get("note"):
            wrong_lines.append(f"    หมายเหตุ: {truth['note']}")
        wrong_lines.append("")
    with io.open(os.path.join(OUT_DIR, "wrong.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(wrong_lines))

    print()
    print(report)
    print()
    print(f"เขียนผลไว้ใน {OUT_DIR}\\  (เปิดด้วย VS Code เพื่อดูภาษาไทยให้ครบ)")
    print(f"  {OUT_DIR}\\wrong.txt  = รายการช่องที่ยังผิด ส่งไฟล์นี้มาได้เลย")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
