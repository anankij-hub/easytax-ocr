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


def normalize_thai_text(text):
    """Some OCR engines (confirmed on Google Vision output from a real
    invoice) emit Thai SARA AM (ำ, U+0E33) as its decomposed two-character
    sequence NIKHAHIT + SARA AA (ํ + า, U+0E4D U+0E32) instead of the single
    precomposed character. The two render identically, but Unicode NFC
    normalization does NOT merge them back (Thai script has no canonical
    decomposition mapping for ำ), so every keyword containing it —
    "จำนวน" (amount), "กำกับ" (as in ใบกำกับภาษี), "จำกัด" (Co., Ltd.), etc. —
    silently fails to match against such OCR output. Collapse the
    decomposed form back to ำ before any other processing; this is safe
    and a no-op on text that already uses the precomposed form."""
    if not text:
        return text
    # Explicit codepoints (not literal Thai characters typed in source) so
    # this is unambiguous no matter how this file itself gets
    # encoded/normalized: ํ NIKHAHIT + า SARA AA -> ำ SARA AM
    return text.replace("ํา", "ำ")

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
    r"Invoice\s*No\.?", r"Tax\s*Invoice\s*No\.?", r"Document\s*No\.?", r"No\.",
]
DATE_KEYWORDS = [r"วันที่", r"Date"]
VAT_KEYWORDS = [r"ภาษีมูลค่าเพิ่ม", r"VAT", r"Vat"]
# Most specific / least ambiguous first. "จำนวนเงิน" (bare, no suffix) is
# deliberately last/lowest-priority — it's also part of the line-items
# table's column header wording on some invoices ("...ราคา/หน่วย ส่วนลด
# จำนวนเงินรวม"), so more specific labels should win when present. It's
# still needed because some receipts literally label the pre-tax subtotal
# just "จำนวนเงิน" / "SUB TOTAL".
SUBTOTAL_KEYWORDS = [
    r"มูลค่าหลังส่วนลด", r"จำนวนเงินหลังหักส่วนลด", r"หลังหักส่วนลด",
    r"ยอดก่อนภาษี", r"มูลค่าก่อนภาษี", r"มูลค่าสินค้า",
    r"รวมเป็นเงิน", r"รวมเงิน", r"After\s*Discount", r"Sub\s*Total", r"จำนวนเงิน",
]
TOTAL_KEYWORDS = [
    r"จำนวนเงิน(?:รวม)?ทั้งสิ้น", r"จำนวนเงินรวมสุทธิ", r"รวมทั้งสิ้น", r"ยอดรวมสุทธิ", r"ยอดรวม",
    r"Grand\s*Total", r"Total\s*Amount", r"Total",
]
BUYER_KEYWORDS = [
    r"นามผู้ซื้อ", r"ชื่อผู้ซื้อ", r"ลูกค้า", r"Customer", r"Bill\s*To",
]
# NOTE: "Buyer Name" is intentionally NOT in this forward-search list — on
# a real invoice it was OCR'd sitting AFTER the buyer name value instead of
# before it, so searching forward from it grabbed unrelated text below.
# extract_buyer_name() handles that specific case separately by checking
# the line *before* "Buyer Name" first.
TAXINV_MARKER = r"ใบกำกับภาษี"
RECEIPT_MARKER = r"ใบเสร็จรับเงิน"

# A line that is clearly part of the line-items table header (not a data
# row, not a totals line) — used to keep totals/VAT extraction from
# misreading header text as a value. Confirmed on a real invoice: a
# bilingual item table can have a SECOND header row further down
# ("จำนวนเงินรวม" / "TOTAL AMOUNT", "ITEM DISCOUNT", "QUANTITY", "UNIT
# PRICE"...) whose column names ("total", "discount", "amount") happen to
# match the same generic keywords used for the invoice's real totals
# section — without recognizing these as header text too, the totals-block
# scanner can lock onto this row plus the first line item's numbers and
# return a completely wrong (but internally consistent) result.
TABLE_HEADER_LINE_RE = re.compile(
    # (?!สุทธิ) so this doesn't collide with the real grand-total label
    # "จำนวนเงินรวมสุทธิ", which legitimately starts with the same prefix.
    r"ลำดับ|รหัสสินค้า|ราคา\s*/\s*หน่วย|ราคาต่อหน่วย|รายการสินค้า|จำนวนเงินรวม(?!สุทธิ)|"
    r"PRODUCT\s*CODE|DESCRIPTION|QUANTITY|UNIT\s*PRICE|ITEM\s*DISCOUNT|TOTAL\s*AMOUNT",
    re.IGNORECASE,
)

# Bilingual invoices often print a field as THREE lines: a Thai label, an
# English sub-label right under it, then the actual value on the next line
# (e.g. "ชื่อผู้ซื้อ" / "Buyer Name" / "คณะบริหารธุรกิจ..."). When a keyword
# search's same-line lookup comes up empty and falls back to scanning the
# next couple of lines, it needs to skip over that English sub-label line
# instead of grabbing it as if it were the value — otherwise fields end up
# populated with literal label text like "Document No." or "Buyer Name".
_LOOKAHEAD_LABEL_BLOCKLIST = {
    "buyer name", "buyer address", "buyer tax id", "buyer branch id",
    "buyer contact person", "buyer contact phone no", "document no",
    "document date", "document ref", "date of ref", "purchase order no",
    "sub total", "bill discount", "after discount", "grand total amount",
    "invoice no", "tax invoice no", "customer", "bill to", "date", "address",
    "no", "name", "phone no", "seller name", "seller address", "vat 7%",
}

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


def _best_match_on_line(rest, value_pattern, require_digit=False):
    """Pick the value on the rest-of-line after a keyword. For numeric
    patterns, Thai invoices usually print the actual amount at the end of
    the line (e.g. 'ภาษีมูลค่าเพิ่ม 7%   140.00'), so prefer the *last*
    match and skip anything that looks like a percentage (N%).

    If EVERY number on the line looks like a percentage, treat that as "no
    real value here" and return None — rather than falling back to
    returning the percentage itself. Previously a line like
    'ภาษีมูลค่าเพิ่ม 7%' (with the actual amount on a different line/column)
    would incorrectly return "7" as the VAT amount and stop the search
    before it ever reached the real number.

    require_digit=True additionally rejects a match that contains no digits
    at all — used for document/invoice numbers, which always contain at
    least one digit, so a plain English word like "Document" (picked up
    from a bilingual label's English line) can't be mistaken for the
    value."""
    matches = list(re.finditer(value_pattern, rest))
    if not matches:
        return None
    if value_pattern is NUM_RE:
        filtered = [mm for mm in matches if not rest[mm.end():mm.end() + 3].strip().startswith("%")]
        if not filtered:
            return None
        return filtered[-1].group(0).strip()
    if require_digit:
        matches = [mm for mm in matches if re.search(r"\d", mm.group(0))]
        if not matches:
            return None
    return matches[0].group(0).strip()


def _find_after_keyword(text, keywords, value_pattern=NUM_RE, window=60, lookahead_lines=2,
                         skip_header_lines=True, require_digit=False):
    """Find the value that appears shortly after one of the given keywords.

    Keywords are tried in priority order: every occurrence of the FIRST
    keyword in the document is checked before moving on to the second
    keyword, etc. This matters because a document can contain more than one
    label that matches *something* in the list — e.g. a real invoice
    printed "เลขที่เอกสาร" (a generic document number) above "เลขที่ใบกำกับภาษี"
    (the actual tax invoice number). A naive top-to-bottom scan that
    returns on the first line matching *any* keyword would grab the wrong
    one just because it happens to appear earlier on the page. Looping
    keyword-first instead makes sure the more specific/preferred label
    always wins regardless of where it sits on the page.

    For each keyword occurrence, checks the same line first, then falls
    back to the next couple of lines (OCR — especially Google Vision on a
    boxed/tabular layout — sometimes puts a label and its value on
    separate lines even though they're the same visual field). Lines that
    look like the line-items table header, or a known bilingual English
    sub-label (see _LOOKAHEAD_LABEL_BLOCKLIST), are skipped during that
    lookahead so a label word can't be mistaken for the actual value.
    Falls back to a raw character-window search if nothing is found."""
    lines = text.splitlines()
    for kw in keywords:
        for i, line in enumerate(lines):
            if skip_header_lines and TABLE_HEADER_LINE_RE.search(line):
                continue
            m = re.search(kw, line, re.IGNORECASE)
            if not m:
                continue
            rest = line[m.end():]
            val = _best_match_on_line(rest, value_pattern, require_digit=require_digit)
            if val:
                return val
            for j in range(1, lookahead_lines + 1):
                if i + j >= len(lines):
                    break
                nxt = lines[i + j]
                if skip_header_lines and TABLE_HEADER_LINE_RE.search(nxt):
                    continue
                if nxt.strip().lower().rstrip(".") in _LOOKAHEAD_LABEL_BLOCKLIST:
                    continue
                val = _best_match_on_line(nxt, value_pattern, require_digit=require_digit)
                if val:
                    return val
    # fallback: search whole text within a character window after the keyword
    for kw in keywords:
        for m in re.finditer(kw, text, re.IGNORECASE):
            window_text = text[m.end():m.end() + window]
            val = _best_match_on_line(window_text, value_pattern, require_digit=require_digit)
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
    val = _find_after_keyword(
        text, INVOICE_NO_KEYWORDS, value_pattern=r"[A-Za-z0-9\-/]{3,}", require_digit=True
    )
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
            # Window needs to be wide enough to skip past an intervening
            # bilingual English sub-label (e.g. "วันที่เอกสาร\nDocument
            # Date\n02/08/2025") without truncating the date itself.
            window_text = text[m.end():m.end() + 60]
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


COMPANY_NAME_HINT_RE = re.compile(r"บริษัท|ห้างหุ้นส่วน|จำกัด|มหาชน|Co\.,?\s*Ltd|Company")


def extract_seller_name(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Prefer a line that actually looks like a registered company name —
    # some invoices print a short logo/brand word (e.g. "Moshi Moshi") as
    # its own line above the real registered name ("บริษัท โมชิ โมชิ รีเทล
    # คอร์ปอเรชั่น จำกัด (มหาชน)"), and a plain "first short line" heuristic
    # grabs the logo text instead of the real name.
    for line in lines[:8]:
        if re.search(TAXINV_MARKER, line) or re.search(RECEIPT_MARKER, line):
            continue
        if re.search(r"\d{10,}", line):
            continue
        if len(line) >= 5 and COMPANY_NAME_HINT_RE.search(line):
            return line
    # fallback: first short-ish non-marker line
    for line in lines[:6]:
        if re.search(TAXINV_MARKER, line) or re.search(RECEIPT_MARKER, line):
            continue
        if re.search(r"\d{10,}", line):
            continue
        if len(line) >= 3:
            return line
    return None


def _looks_like_value_line(line):
    line = line.strip()
    return bool(line) and line.lower() not in _LOOKAHEAD_LABEL_BLOCKLIST and len(line) >= 3


def extract_buyer_name(text):
    lines = text.splitlines()
    # Reversed-order case, confirmed on a real bilingual invoice: OCR
    # printed the buyer name value BEFORE its "Buyer Name" English
    # sub-label (with the Thai label above the value garbled beyond
    # recognition), instead of label-then-value like every other field.
    # If "Buyer Name" is found, check the line right above it first — if
    # it looks like real Thai text (not a label/blocklist word), it's the
    # value, regardless of what comes after.
    for i, line in enumerate(lines):
        if line.strip().lower() == "buyer name" and i > 0:
            prev = lines[i - 1].strip()
            # Only treat the previous line as the value if it isn't itself
            # a recognizable label (e.g. "ชื่อผู้ซื้อ") — that would mean
            # this document actually uses the normal label-then-value
            # order and "Buyer Name" is just the English half of the
            # label pair, not a value marker to look backward from.
            prev_is_label = any(re.search(kw, prev, re.IGNORECASE) for kw in BUYER_KEYWORDS)
            if not prev_is_label and _looks_like_value_line(prev) and re.search(r"[ก-๙]", prev):
                return prev

    val = _find_after_keyword(text, BUYER_KEYWORDS, value_pattern=r"[^\n]{3,60}")
    if not val:
        return None
    val = val.strip()
    # The keyword match only skips past the label itself (e.g. "ลูกค้า"), so
    # a layout like "ชื่อลูกค้า : บริษัท A จำกัด" leaves a leading ":" in the
    # captured value — strip that (and other separator punctuation) off.
    val = re.sub(r"^[:：\-–]\s*", "", val).strip()
    return val or None


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


# Some OCR engines (Google Vision included) read a boxed totals section as
# two separate runs of lines — every label first, then every value — rather
# than one "label   value" pair per line, when the label column and value
# column get grouped as separate text blocks. Same-line/window matching
# then grabs whichever number is textually nearest to a label, which is
# often the WRONG number (and can make subtotal/VAT/total all resolve to
# the same figure — the first value in the value run). This block detects
# that shape and pairs the Nth label with the Nth value instead.
#
# The bare word "จำนวนเงิน" (in SUBTOTAL_KEYWORDS) is deliberately excluded
# from this primary list and checked only as a last-resort fallback (see
# _classify_totals_label) — it's a substring of several TOTAL labels too
# ("จำนวนเงินทั้งสิ้น", "จำนวนเงินรวมสุทธิ"), so checking it at the same
# priority as everything else would misclassify a real total line as a
# subtotal just because "จำนวนเงิน" happens to also be a prefix of it.
_TOTALS_BLOCK_KEYS = [
    ("subtotal", [kw for kw in SUBTOTAL_KEYWORDS if kw != r"จำนวนเงิน"]),
    ("discount", [r"ส่วนลด", r"Discount"]),
    ("vat", VAT_KEYWORDS),
    ("total", TOTAL_KEYWORDS),
]
_TOTALS_BLOCK_FALLBACK_KEY = ("subtotal", [r"จำนวนเงิน"])

PURE_NUMBER_LINE_RE = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?\s*%?$")


def _classify_totals_label(line):
    for key, patterns in _TOTALS_BLOCK_KEYS:
        for pat in patterns:
            if re.search(pat, line, re.IGNORECASE):
                return key
    fallback_key, fallback_patterns = _TOTALS_BLOCK_FALLBACK_KEY
    for pat in fallback_patterns:
        if re.search(pat, line, re.IGNORECASE):
            return fallback_key
    return None


def _extract_totals_block(text):
    """Look for a run of consecutive recognizable total-related label lines
    immediately followed by a run of the same number of pure-number lines,
    and pair them up by position. Returns raw string values keyed by
    "subtotal"/"discount"/"vat"/"total" (only for keys actually found), or
    {} if the text doesn't have this shape — callers should fall back to
    _find_after_keyword in that case.

    Bilingual invoices print each field as a Thai label line *and* an
    English label line (e.g. "ภาษีมูลค่าเพิ่ม 7%" then "VAT 7%"), and both
    may independently match the same key's patterns. Two consecutive lines
    that classify to the *same* key are collapsed into a single label so
    they still count as one field, keeping the label count aligned with
    the value count.

    Real OCR output isn't perfectly clean — a confirmed real example had
    an English sub-label OCR'd with a typo ("AFTER DISCOINT" instead of
    "AFTER DISCOUNT"). A single unrecognized line like that shouldn't kill
    the whole label run, so up to 2 consecutive unclassifiable lines are
    skipped rather than treated as the end of the run; more than that and
    we've probably wandered into unrelated content, so the run stops."""
    lines = [l.strip() for l in text.splitlines()]
    n = len(lines)
    for start in range(n):
        labels = []
        j = start
        unclassified_streak = 0
        while (j < n and lines[j] and not PURE_NUMBER_LINE_RE.match(lines[j])
               and not TABLE_HEADER_LINE_RE.search(lines[j])):
            key = _classify_totals_label(lines[j])
            if key is not None:
                if not labels or labels[-1] != key:
                    labels.append(key)
                unclassified_streak = 0
            else:
                unclassified_streak += 1
                if unclassified_streak > 2:
                    break
            j += 1
        if len(labels) < 2:
            continue
        values = []
        k = j
        while k < n and lines[k] and PURE_NUMBER_LINE_RE.match(lines[k]):
            values.append(lines[k])
            k += 1
        if len(values) == len(labels):
            result = {}
            for key, val in zip(labels, values):
                result[key] = val  # a later same-key label (e.g. the
                # post-discount subtotal) intentionally overwrites an
                # earlier one, matching _find_after_keyword's own priority
            return result
    return {}


# Some invoices' document-info box (เลขที่เอกสาร/วันที่เอกสาร/เลขที่เอกสารอ้างอิง/
# วันที่เอกสารอ้างอิง/เลขที่ใบสั่งซื้อ) gets OCR'd the same column-major way as
# the totals box: ALL the label lines (Thai+English pairs) first, then ALL
# the value lines after — and confirmed on a real invoice, this run can be
# up to 10 label lines before the first value, far past a small lookahead.
# Unlike the totals box, a trailing field is often blank (no printed value
# at all, e.g. an empty Purchase Order No.), so the value run can be
# SHORTER than the label run — pair up to the shorter length instead of
# requiring an exact match.
_DOC_INFO_BLOCK_KEYS = [
    ("doc_no", [r"เลขที่เอกสาร(?!อ้างอิง)", r"Document\s*No"]),
    ("doc_date", [r"วันที่เอกสาร(?!อ้างอิง)", r"Document\s*Date"]),
    ("doc_ref_no", [r"เลขที่เอกสารอ้างอิง", r"Document\s*Ref"]),
    ("doc_ref_date", [r"วันที่เอกสารอ้างอิง", r"Date\s*of\s*Ref"]),
    ("po_no", [r"เลขที่ใบสั่งซื้อ", r"Purchase\s*Order\s*No"]),
]

# A "value" line here is a single alphanumeric token with no spaces (a doc
# number, a reference number, or a dd/mm/yyyy date) — deliberately narrower
# than PURE_NUMBER_LINE_RE since these values aren't always pure digits.
DOC_VALUE_LINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/.]*$")


def _classify_doc_info_label(line):
    for key, patterns in _DOC_INFO_BLOCK_KEYS:
        for pat in patterns:
            if re.search(pat, line, re.IGNORECASE):
                return key
    return None


def _extract_doc_info_block(text):
    """Same idea as _extract_totals_block but for the document-info box —
    see the comment above _DOC_INFO_BLOCK_KEYS. Returns raw string values
    keyed by "doc_no"/"doc_date"/"doc_ref_no"/"doc_ref_date"/"po_no", or {}
    if the text doesn't have this shape."""
    lines = [l.strip() for l in text.splitlines()]
    n = len(lines)
    for start in range(n):
        labels = []
        j = start
        unclassified_streak = 0
        # Stop as soon as we reach a value-shaped line — that's the real
        # transition from labels to values. Tolerating it as just another
        # "unclassified" skip (like a stray typo) would eat into the front
        # of the value run and shift every label/value pairing off by one.
        while j < n and lines[j] and not DOC_VALUE_LINE_RE.match(lines[j]):
            key = _classify_doc_info_label(lines[j])
            if key is not None:
                if not labels or labels[-1] != key:
                    labels.append(key)
                unclassified_streak = 0
            else:
                unclassified_streak += 1
                if unclassified_streak > 2:
                    break
            j += 1
        if len(labels) < 2:
            continue
        values = []
        k = j
        while k < n and lines[k] and DOC_VALUE_LINE_RE.match(lines[k]):
            values.append(lines[k])
            k += 1
        if not values:
            continue
        return dict(zip(labels, values))  # zip stops at the shorter list,
        # so a blank trailing field (fewer values than labels) just isn't
        # included in the result rather than causing a mismatch
    return {}


def extract_fields(text, ocr_confidence=None):
    """Main entry point: raw OCR text -> structured dict."""
    text = normalize_thai_text(text or "")
    date_raw, date_iso = extract_date(text)
    seller_tax_id = extract_tax_id(text)
    seller_name = extract_seller_name(text)
    buyer_name = extract_buyer_name(text)

    doc_info_block = _extract_doc_info_block(text)
    invoice_no = doc_info_block.get("doc_no") or extract_invoice_no(text)

    totals_block = _extract_totals_block(text)
    subtotal = (_clean_number(totals_block["subtotal"]) if "subtotal" in totals_block
                else _clean_number(_find_after_keyword(text, SUBTOTAL_KEYWORDS)))
    vat = (_clean_number(totals_block["vat"]) if "vat" in totals_block
           else _clean_number(_find_after_keyword(text, VAT_KEYWORDS)))
    total = (_clean_number(totals_block["total"]) if "total" in totals_block
             else _clean_number(_find_after_keyword(text, TOTAL_KEYWORDS)))

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
        "ocr_confidence": ocr_confidence,
        "_has_tax_invoice_marker": bool(re.search(TAXINV_MARKER, text)),
    }
    fields["doc_type"] = classify_doc_type(fields)
    reasons = build_review_reasons(fields)
    fields["needs_review"] = bool(reasons)
    fields["review_reason"] = "; ".join(reasons) if reasons else None
    return fields


# A document-title line looks like "ใบกำกับภาษี", "ใบกำกับภาษี/ใบเสร็จรับเงิน
# (ต้นฉบับ)", "สำเนาใบกำกับภาษี" etc — i.e. the *whole line* is essentially
# just the title. This deliberately does NOT match field-label lines like
# "เลขที่ใบกำกับภาษี: IV123" or "วันที่ใบกำกับภาษี 07/12/2025", which contain
# the same marker word but are part of a data field, not a new document.
DOC_TITLE_LINE_RE = re.compile(
    r"^\s*(?:ต้นฉบับ\s*)?(?:สำเนา\s*)?ใบกำกับภาษี\s*(?:/\s*ใบเสร็จรับเงิน)?\s*(?:\([^)]{0,20}\))?\s*$"
)


def split_multi_invoice_text(text):
    """Heuristic splitter for a single OCR text blob (e.g. one scanned page
    or PDF) that may contain more than one 'ใบกำกับภาษี' document laid out
    on the same page. Splits only at lines that are themselves a document
    title, not every occurrence of the word 'ใบกำกับภาษี' anywhere in the
    text (field labels like 'เลขที่ใบกำกับภาษี' also contain that word and
    must NOT trigger a split). Still just a heuristic — no real layout
    understanding — so always let the user review the result."""
    text = normalize_thai_text(text or "")
    lines = text.splitlines(keepends=True)
    offsets = []
    pos = 0
    for line in lines:
        if DOC_TITLE_LINE_RE.match(line.strip()):
            offsets.append(pos)
        pos += len(line)
    if len(offsets) <= 1:
        return [text]
    chunks = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(text)
        chunks.append(text[start:end])
    return chunks
