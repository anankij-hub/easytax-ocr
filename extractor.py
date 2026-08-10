"""Rule-based field extraction for Thai tax invoices / receipts (ใบกำกับภาษี/ใบเสร็จ).

This module takes raw OCR text and pulls out the fields required by
มาตรา 86/4 แห่งประมวลรัษฎากร, classifies the document as เต็มรูป (full form,
VAT-deductible) or ย่อ (abbreviated, not VAT-deductible), and flags records
that need human review.

Because this relies on regex/keyword heuristics instead of an LLM, it will
not be as robust as the Claude-based extractor to unusual layouts. Add new
keyword variants to the *_KEYWORDS lists below as you encounter real vendor
documents that fail to parse.
"""
import re
import datetime

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

THAI_MONTHS = {
    "มกราคม": 1, "ม.ค.": 1, "ม.ค": 1,
    "กุมภาพันธ์": 2, "ก.พ.": 2, "ก.พ": 2,
    "มีนาคม": 3, "มี.ค.": 3, "มี.ค": 3,
    "เมษายน": 4, "เม.ย.": 4, "เม.ย": 4,
    "พฤษภาคม": 5, "พ.ค.": 5, "พ.ค": 5,
    "มิถุนายน": 6, "มิ.ย.": 6, "มิ.ย": 6,
    "กรกฎาคม": 7, "ก.ค.": 7, "ก.ค": 7,
    "สิงหาคม": 8, "ส.ค.": 8, "ส.ค": 8,
    "กันยายน": 9, "ก.ย.": 9, "ก.ย": 9,
    "ตุลาคม": 10, "ต.ค.": 10, "ต.ค": 10,
    "พฤศจิกายน": 11, "พ.ย.": 11, "พ.ย": 11,
    "ธันวาคม": 12, "ธ.ค.": 12, "ธ.ค": 12,
}

INVOICE_NO_KEYWORDS = [
    r"เลขที่ใบกำกับภาษี", r"เลขที่เอกสาร", r"เลขที่ใบเสร็จ", r"เลขที่",
    r"Invoice\s*No\.?", r"Tax\s*Invoice\s*No\.?", r"No\.",
]
DATE_KEYWORDS = [r"วันที่", r"Date"]
VAT_KEYWORDS = [r"ภาษีมูลค่าเพิ่ม", r"VAT", r"Vat"]
SUBTOTAL_KEYWORDS = [r"มูลค่าสินค้า", r"รวมเป็นเงิน", r"รวมเงิน", r"Subtotal", r"จำนวนเงิน"]
TOTAL_KEYWORDS = [
    r"จำนวนเงินรวมทั้งสิ้น", r"รวมทั้งสิ้น", r"ยอดรวมสุทธิ", r"ยอดรวม",
    r"Grand\s*Total", r"Total\s*Amount", r"Total",
]
BUYER_KEYWORDS = [r"นามผู้ซื้อ", r"ชื่อผู้ซื้อ", r"ลูกค้า", r"Customer", r"Bill\s*To"]
TAXINV_MARKER = r"ใบกำกับภาษี"
RECEIPT_MARKER = r"ใบเสร็จรับเงิน"

NUM_RE = r"[-+]?\d[\d,]*(?:\.\d+)?"
TAXID_RE = re.compile(r"(\d[\s-]?\d{4}[\s-]?\d{5}[\s-]?\d{2}[\s-]?\d)")
TAXID_PLAIN_RE = re.compile(r"\b\d{13}\b")


def _clean_number(s):
    if s is None:
        return None
    s = s.translate(THAI_DIGITS).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _best_match_on_line(rest, value_pattern):
    """Pick the value on the rest-of-line after a keyword. For numeric
    patterns, Thai invoices usually print the actual amount at the end of
    the line (e.g. 'ภาษีมูลค่าเพิ่ม 7%   140.00'), so prefer the *last*
    match and skip anything that looks like a percentage (N%)."""
    matches = list(re.finditer(value_pattern, rest))
    if not matches:
        return None
    if value_pattern is NUM_RE:
        filtered = [mm for mm in matches if not rest[mm.end():mm.end() + 1].strip().startswith("%")]
        candidates = filtered or matches
        return candidates[-1].group(0).strip()
    return matches[0].group(0).strip()


def _find_after_keyword(text, keywords, value_pattern=NUM_RE, window=40):
    """Find the value that appears shortly after one of the given keywords,
    searching line by line first, then a window fallback."""
    for line in text.splitlines():
        for kw in keywords:
            m = re.search(kw, line, re.IGNORECASE)
            if m:
                rest = line[m.end():]
                val = _best_match_on_line(rest, value_pattern)
                if val:
                    return val
    # fallback: search whole text within a character window after the keyword
    for kw in keywords:
        for m in re.finditer(kw, text, re.IGNORECASE):
            window_text = text[m.end():m.end() + window]
            val = _best_match_on_line(window_text, value_pattern)
            if val:
                return val
    return None


def validate_thai_tax_id(tax_id):
    """Checksum validation for a 13-digit Thai taxpayer ID (mod 11)."""
    if not tax_id:
        return False
    digits = re.sub(r"\D", "", tax_id)
    if len(digits) != 13:
        return False
    total = sum(int(d) * (13 - i) for i, d in enumerate(digits[:12]))
    check = (11 - (total % 11)) % 10
    return check == int(digits[12])


def extract_tax_id(text):
    for m in TAXID_RE.finditer(text):
        candidate = re.sub(r"\D", "", m.group(1))
        if len(candidate) == 13:
            return candidate
    for m in TAXID_PLAIN_RE.finditer(text):
        return m.group(0)
    return None


def extract_invoice_no(text):
    val = _find_after_keyword(text, INVOICE_NO_KEYWORDS, value_pattern=r"[A-Za-z0-9\-/]{3,}")
    return val


def _parse_thai_date(raw):
    """Try to parse a Thai-formatted date string into ISO yyyy-mm-dd.
    Handles dd/mm/yyyy (พ.ศ. or ค.ศ.) and 'dd เดือน ปี' formats."""
    raw = raw.translate(THAI_DIGITS).strip()

    m = re.match(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2500 if y > 30 else 2000  # heuristic 2-digit year
        if y > 2400:
            y -= 543  # พ.ศ. -> ค.ศ.
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            return None

    for name, mo in THAI_MONTHS.items():
        m2 = re.search(r"(\d{1,2})\s*" + re.escape(name) + r"\s*(\d{4})", raw)
        if m2:
            d, y = int(m2.group(1)), int(m2.group(2))
            if y > 2400:
                y -= 543
            try:
                return datetime.date(y, mo, d).isoformat()
            except ValueError:
                return None
    return None


def extract_date(text):
    for kw in DATE_KEYWORDS:
        for m in re.finditer(kw, text):
            window_text = text[m.end():m.end() + 30]
            dm = re.search(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}", window_text)
            if dm:
                iso = _parse_thai_date(dm.group(0))
                return dm.group(0), iso
            for name in THAI_MONTHS:
                dm2 = re.search(r"\d{1,2}\s*" + re.escape(name) + r"\s*\d{4}", window_text)
                if dm2:
                    iso = _parse_thai_date(dm2.group(0))
                    return dm2.group(0), iso
    # fallback: any date-looking token in the whole document
    dm = re.search(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}", text)
    if dm:
        return dm.group(0), _parse_thai_date(dm.group(0))
    return None, None


def extract_seller_name(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:6]:
        if re.search(TAXINV_MARKER, line) or re.search(RECEIPT_MARKER, line):
            continue
        if re.search(r"\d{10,}", line):
            continue
        if len(line) >= 3:
            return line
    return None


def extract_buyer_name(text):
    val = _find_after_keyword(text, BUYER_KEYWORDS, value_pattern=r"[^\n]{3,60}")
    return val.strip() if val else None


def classify_doc_type(fields):
    """เต็มรูป ต้องมีเลขผู้เสียภาษีผู้ขายที่ผ่าน checksum + เลขที่ใบกำกับ + ชื่อผู้ซื้อ
    ถ้าขาดอย่างใดอย่างหนึ่ง ถือเป็นใบย่อ (หัก VAT ซื้อไม่ได้)."""
    has_marker = fields.get("_has_tax_invoice_marker")
    valid_tax_id = fields.get("seller_tax_id") and validate_thai_tax_id(fields["seller_tax_id"])
    has_invoice_no = bool(fields.get("invoice_no"))
    has_buyer = bool(fields.get("buyer_name"))
    if has_marker and valid_tax_id and has_invoice_no and has_buyer:
        return "เต็มรูป"
    return "ย่อ"


def build_review_reasons(fields):
    reasons = []
    if not fields.get("invoice_no"):
        reasons.append("ไม่พบเลขที่ใบกำกับภาษี")
    if not fields.get("invoice_date_iso") and not fields.get("invoice_date_raw"):
        reasons.append("ไม่พบวันที่")
    if not fields.get("seller_tax_id"):
        reasons.append("ไม่พบเลขประจำตัวผู้เสียภาษีผู้ขาย")
    elif not validate_thai_tax_id(fields["seller_tax_id"]):
        reasons.append("เลขผู้เสียภาษีไม่ผ่านการตรวจสอบ checksum")
    if fields.get("total") is None:
        reasons.append("ไม่พบยอดรวม")
    if fields.get("ocr_confidence") is not None and fields["ocr_confidence"] < 60:
        reasons.append(f"ความมั่นใจ OCR ต่ำ ({fields['ocr_confidence']:.0f}%)")
    return reasons


LINE_ITEM_RE = re.compile(
    r"^(?P<desc>.{2,60}?)\s+"
    r"(?P<qty>\d+(?:\.\d{1,2})?)\s+"
    r"(?P<price>[\d,]+\.\d{2})\s+"
    r"(?P<amount>[\d,]+\.\d{2})\s*$"
)

LINE_ITEM_SKIP_KEYWORDS = (
    SUBTOTAL_KEYWORDS + TOTAL_KEYWORDS + VAT_KEYWORDS +
    [r"ส่วนลด", r"Discount", r"หัก", r"ยอดสุทธิ"]
)


def extract_line_items(text):
    """Best-effort extraction of a product/service table from OCR text.
    Looks for lines shaped like 'description  qty  unit_price  amount'.
    This is a heuristic (no table/column detection), so it works best on
    invoices with a simple one-row-per-line item table and will miss
    multi-line descriptions or unusual column layouts — always let the
    user review/edit the result."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(re.search(kw, line, re.IGNORECASE) for kw in LINE_ITEM_SKIP_KEYWORDS):
            continue
        m = LINE_ITEM_RE.match(line)
        if not m:
            continue
        qty = _clean_number(m.group("qty"))
        price = _clean_number(m.group("price"))
        amount = _clean_number(m.group("amount"))
        items.append({
            "description": m.group("desc").strip(),
            "qty": qty,
            "unit_price": price,
            "amount": amount,
        })
    return items


def extract_fields(text, ocr_confidence=None):
    """Main entry point: raw OCR text -> structured dict."""
    text = text or ""
    invoice_no = extract_invoice_no(text)
    date_raw, date_iso = extract_date(text)
    seller_tax_id = extract_tax_id(text)
    seller_name = extract_seller_name(text)
    buyer_name = extract_buyer_name(text)
    subtotal = _clean_number(_find_after_keyword(text, SUBTOTAL_KEYWORDS))
    vat = _clean_number(_find_after_keyword(text, VAT_KEYWORDS))
    total = _clean_number(_find_after_keyword(text, TOTAL_KEYWORDS))
    line_items = extract_line_items(text)

    fields = {
        "invoice_no": invoice_no,
        "invoice_date_raw": date_raw,
        "invoice_date_iso": date_iso,
        "seller_name": seller_name,
        "seller_tax_id": seller_tax_id,
        "buyer_name": buyer_name,
        "subtotal": subtotal,
        "vat": vat,
        "total": total,
        "line_items": line_items,
        "ocr_confidence": ocr_confidence,
        "_has_tax_invoice_marker": bool(re.search(TAXINV_MARKER, text)),
    }
    fields["doc_type"] = classify_doc_type(fields)
    reasons = build_review_reasons(fields)
    fields["needs_review"] = bool(reasons)
    fields["review_reason"] = "; ".join(reasons) if reasons else None
    return fields


def split_multi_invoice_text(text):
    """Very simple heuristic splitter for a single OCR text blob (e.g. one
    scanned page/PDF) that may contain more than one 'ใบกำกับภาษี' document.
    Splits at each occurrence of the marker keyword. This is far less
    reliable than an LLM-based split and should be reviewed by a human."""
    positions = [m.start() for m in re.finditer(TAXINV_MARKER, text)]
    if len(positions) <= 1:
        return [text]
    chunks = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        chunks.append(text[start:end])
    return chunks
