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
    r"ยอดก่อนภาษี", r"มูลค่าก่อนภาษี", r"มูลค่าสินค้า", r"ราคารวมสินค้า",
    r"รวมเป็นเงิน", r"รวมเงิน", r"After\s*Discount", r"Sub\s*Total", r"จำนวนเงิน",
]
# "สิ้?น" — the MAI THO on สิ้น is optional on purpose. Confirmed on a real
# invoice: Vision dropped the tone mark and read the grand-total label as
# "ราคารวมทั้งสิน", which matched no keyword at all, so the totals block
# failed to pair up and the amounts came out of unrelated table cells.
# Thai tone marks are small and the first thing a scan loses.
TOTAL_KEYWORDS = [
    r"จำนวนเงิน(?:รวม)?ทั้งสิ้?น", r"จำนวนเงินรวมสุทธิ", r"รวมทั้งสิ้?น", r"ยอดรวมสุทธิ", r"ยอดรวม",
    r"Grand\s*Total", r"Total\s*Amount", r"Total",
]
# "ลูกค้า" carries two negative lookbehinds so it matches the buyer-name
# label ("ชื่อลูกค้า") but NOT a customer *code* field ("รหัสลูกค้า",
# "เลขที่ลูกค้า") — those hold a short numeric/alphanumeric code, which the
# forward search would otherwise happily return as the buyer's name.
BUYER_KEYWORDS = [
    r"นามผู้ซื้อ", r"ชื่อผู้ซื้อ", r"(?<!รหัส)(?<!เลขที่)ลูกค้า", r"Customer", r"Bill\s*To",
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
    r"ลำดับ|รหัสสินค้า|ราคา\s*/\s*หน่วย|ราคาต่อหน่วย|รายการสินค้า|จำนวนเงินรวม(?!สุทธิ|ทั้งสิ้?น)|"
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


# Thai invoices very often write a whole-baht amount as "1,300.-" (and
# sometimes "1,300,-"), where the dash stands in for the satang rather than
# being a minus sign. Confirmed on a real invoice where EVERY amount was
# printed this way, which made the extractor report no amounts at all.
TRAILING_DASH_SATANG_RE = re.compile(r"\s*[.,]-\s*$")


def _clean_number(s):
    if s is None:
        return None
    s = TRAILING_DASH_SATANG_RE.sub("", s.translate(THAI_DIGITS).strip())
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# One column heading of an items table, alone on its line — what a
# column-major OCR read produces instead of one "ลำดับ รายการ จำนวน ..."
# header row. TABLE_HEADER_LINE_RE can't catch these on its own because
# several are ordinary words that also label real fields.
COLUMN_HEADER_WORD_RE = re.compile(
    r"^(?:ลำดับ(?:ที่)?|ที่|รหัสสินค้า|รหัส|รายการ(?:สินค้า)?(?:\s*/\s*บริการ)?|รายละเอียด|"
    r"จำนวน|จำนวนเงิน|หน่วย|ราคา(?:\s*/\s*หน่วย|ต่อหน่วย)?|ราคาสุทธิ|ส่วนลด|มูลค่า|"
    r"No\.?|Item|Qty|Unit|Price|Amount|Description|Discount|Total)\s*$",
    re.IGNORECASE,
)


def _is_table_column_header(lines, i):
    """True when line i is an items-table column heading rather than a field
    label. A bare "จำนวนเงิน" is genuinely ambiguous — on some receipts it
    labels the pre-tax subtotal (which is why it's in SUBTOTAL_KEYWORDS),
    but in a column-major read of an items table it's the last column's
    heading, with the first row's line number on the next line. Confirmed
    live: that "1" was reported as ยอดก่อนภาษี.

    A heading never stands alone, so require a neighbour that is also a
    bare heading word — a real "จำนวนเงิน 2,000.00" totals line has its
    value on the line and no such company."""
    if not COLUMN_HEADER_WORD_RE.match(lines[i].strip()):
        return False
    for j in (i - 2, i - 1, i + 1, i + 2):
        if 0 <= j < len(lines) and j != i and COLUMN_HEADER_WORD_RE.match(lines[j].strip()):
            return True
    return False


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
            if skip_header_lines and (TABLE_HEADER_LINE_RE.search(line)
                                      or _is_table_column_header(lines, i)):
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
                if skip_header_lines and (TABLE_HEADER_LINE_RE.search(nxt)
                                          or _is_table_column_header(lines, i + j)):
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


def _find_number_above_keyword(text, keywords, exclude=(), max_lines_up=4):
    """Find a number printed just ABOVE one of the given labels.

    Ground truth from the live app (บริษัท รจนา invoice, IV1400768-305):
    Vision emitted the totals column with the first value detached from its
    label and placed above it, with an unrelated word in between —

        36,728.97
        หมายเหตุ
        ราคารวมสินค้า (บาท)
        ภาษีมูลค่าเพิ่ม 7%
        2,571.03

    A forward search from "ราคารวมสินค้า" therefore skipped past its own
    value and returned the VAT figure two lines down, which is how ยอดก่อนภาษี
    and VAT both ended up as 2,571.03 on screen.

    `exclude` holds figures already claimed by other fields, so the nearest
    number above can't simply be another field's value read a second time.
    Stops at another totals label, whose value this would be, not ours."""
    lines = text.splitlines()
    for kw in keywords:
        for i, line in enumerate(lines):
            if TABLE_HEADER_LINE_RE.search(line) or not re.search(kw, line, re.IGNORECASE):
                continue
            for j in range(1, max_lines_up + 1):
                k = i - j
                if k < 0:
                    break
                prev = lines[k].strip()
                if not prev:
                    continue
                if PURE_NUMBER_LINE_RE.match(prev):
                    val = _clean_number(prev)
                    if val is not None and not any(
                        e is not None and abs(val - e) < 0.005 for e in exclude
                    ):
                        return val
                    break  # nearest number above is already another field's
                if _classify_totals_label(prev) is not None or TABLE_HEADER_LINE_RE.search(prev):
                    break
    return None


def has_valid_tax_id_format(tax_id):
    """Just checks the taxpayer ID is 13 digits — no mod-11 checksum
    validation. (Checksum validation was removed on request: extracting
    the number correctly is enough, it doesn't need to also pass a
    checksum to be accepted.)"""
    if not tax_id:
        return False
    digits = re.sub(r"\D", "", tax_id)
    return len(digits) == 13


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


# Labels that belong to some OTHER field. Two uses when hunting for the
# buyer name: (1) a boxed layout often gets OCR'd with the buyer box and
# the neighbouring document box merged onto one line ("ชื่อลูกค้า : บริษัท A
# จำกัด  เลขที่ใบกำกับภาษี IV0100168-99") — everything from the next label
# onward must be cut off; (2) when the value isn't on the label's own line
# and we scan the following lines, a line that *starts* with one of these
# is a different field (the buyer's address, the invoice number, ...), not
# the buyer's name.
OTHER_FIELD_LABEL_RE = re.compile(
    r"เลขที่ใบกำกับภาษี|เลขที่ใบเสร็จ|เลขที่เอกสาร|เลขที่ใบสั่ง|ใบสั่งซื้อเลขที่|ใบสั่งขายเลขที่|"
    r"วันที่|วันครบกำหนด|เลขประจำตัวผู้เสียภาษี|เลขผู้เสียภาษี|ที่อยู่|โทร|แฟกซ์|"
    r"รหัสพนักงาน|รหัสลูกค้า|ขนส่งโดย|หน้า\s*\d|"
    r"Tax\s*ID|Invoice\s*No|Document\s*(?:No|Date|Ref)|Address|Tel\b|Fax|Page\s*\d",
    re.IGNORECASE,
)

# A captured buyer name that is nothing but digits/punctuation — a line
# number from the items table ("1"), a salesperson code ("001-H"), a page
# marker ("1/1"), a bare taxpayer ID — is never a real name. This was a
# live bug: the value pattern used for names ([^\n]{3,60}) counts the
# surrounding whitespace toward its 3-character minimum, so a padded
# column cell like "  1  " passed the length check and then stripped down
# to "1", which is what ended up in the ชื่อผู้ซื้อ box on screen.
_BUYER_JUNK_VALUE_RE = re.compile(r"^[\d\s,.:/\-–#()%]+$")

# The document's own header furniture — the title, the branch-of-issue line
# ("สาขาที่ออก ใบกำกับภาษี/ใบเสร็จรับเงิน : สำนักงานใหญ่"), the page marker.
# Confirmed on the รจนา invoice from the live app: Google Vision reads that
# boxed layout column-major, so the top-right header text is emitted
# BETWEEN the "ชื่อลูกค้า" label and its value — a forward scan then reads
# the header as the buyer's name. None of this text is ever part of a name,
# so a line containing it is never a candidate.
DOC_FURNITURE_RE = re.compile(
    r"ใบกำกับภาษี|ใบเสร็จรับเงิน|ใบแจ้งหนี้|ใบส่งของ|ต้นฉบับ|สำเนา|สาขาที่ออก|หน้า\s*\d|"
    r"TAX\s*INVOICE|RECEIPT|INVOICE|ORIGINAL|COPY|Page\s*\d",
    re.IGNORECASE,
)

# What a buyer actually is on a Thai invoice: a juristic person, a shop, a
# titled individual, or a public body. Used to PREFER a candidate rather
# than to require one — when several lines in the window could be the
# value, the one that reads like an entity name is the right answer, and
# for the รจนา invoice this is what separates "บริษัท A จำกัด" from the
# header line sitting above it in the OCR stream.
BUYER_ENTITY_HINT_RE = re.compile(
    r"บริษัท|ห้างหุ้นส่วน|หจก|บจก|ร้าน|คุณ|นาย|นาง|นางสาว|ด\.ช\.|ด\.ญ\.|คณะ|มหาวิทยาลัย|"
    r"วิทยาลัย|โรงเรียน|โรงพยาบาล|สำนักงาน|องค์การ|องค์กร|กรม|กระทรวง|เทศบาล|สหกรณ์|"
    r"มูลนิธิ|สมาคม|Co\.,?\s*Ltd|Ltd|P(?:ublic)?\s*Co|Company|Corp|Foundation|University|School",
    re.IGNORECASE,
)


# An address line is never the buyer's NAME, but it sits right next to the
# name in every buyer box and is the most common thing to grab by mistake
# when the name itself isn't where the scan expects it. Confirmed on the
# รจนา invoice: the third line of the customer box, "กรุงเทพมหานคร 10900",
# came out as the buyer name. Matches a line that starts with an address
# component, or that ends in a 5-digit postcode.
ADDRESS_LINE_RE = re.compile(
    r"^(?:กรุงเทพ|จังหวัด|จ\.|อำเภอ|อ\.|ตำบล|ต\.|เขต|แขวง|ถนน|ถ\.|ซอย|ซ\.|หมู่|บ้านเลขที่|"
    r"เลขที่\s*\d|\d+/\d+|Moo\b|Soi\b|Road\b|Rd\.)|\d{5}\s*$",
    re.IGNORECASE,
)


def _norm_name(name):
    """Squash a name down for comparison — spaces and bracketed suffixes
    like '(สำนักงานใหญ่)' vary between how the seller's name is printed in
    the letterhead and how it appears elsewhere on the page."""
    if not name:
        return ""
    return re.sub(r"[\s()（）.,\-–:]+", "", name).lower()


def _is_seller_name(val, seller_name):
    """The buyer is never the seller. OCR that scrambles reading order can
    put the letterhead company name inside the buyer label's search window,
    and accepting it would wrongly certify the document as เต็มรูป with the
    wrong party recorded as the buyer."""
    a, b = _norm_name(val), _norm_name(seller_name)
    if not a or not b:
        return False
    return a == b or (len(a) >= 8 and len(b) >= 8 and (a in b or b in a))


def _clean_buyer_value(val):
    """Strip separator punctuation off the front of a captured buyer name
    and cut it at the next field's label if OCR merged two boxes together."""
    val = (val or "").strip()
    val = re.sub(r"^[:：\-–]+\s*", "", val).strip()
    # A bilingual label pair prints both halves before the value
    # ("ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด"). The keyword match only
    # consumes the Thai half, leaving "/Customer Name : " glued to the front
    # of the name — drop a leading run of Latin label words up to its colon.
    val = re.sub(r"^[/|\-–]?\s*[A-Za-z][A-Za-z.\s]{0,30}[:：]\s*", "", val).strip()
    m = OTHER_FIELD_LABEL_RE.search(val)
    if m and m.start() > 0:
        val = val[:m.start()]
    return val.strip().strip(":：-–").strip()


def _is_plausible_buyer_name(val):
    """A buyer name must be real text: at least two consecutive letters and
    not just numbers/punctuation, not a bare label word. Rejecting instead
    of returning junk matters because the caller keeps searching — a bad
    candidate on the label's own line must not stop the scan before the
    line that actually holds the name."""
    if not val or len(val) < 3:
        return False
    if val.lower().rstrip(".") in _LOOKAHEAD_LABEL_BLOCKLIST:
        return False
    if _BUYER_JUNK_VALUE_RE.match(val):
        return False
    if DOC_FURNITURE_RE.search(val):
        return False
    return bool(re.search(r"[ก-๙A-Za-z]{2,}", val))


def _skip_as_buyer_candidate(line):
    """Lines a value can never be hiding in — another field's label, an
    English sub-label, an items-table header, the document's own header
    text, or a bare number. Skipped 'for free': they don't count against
    the search window, because a column-major OCR read can stack a whole
    run of them between a label and its value."""
    line = line.strip()
    if not line:
        return True
    if TABLE_HEADER_LINE_RE.search(line) or DOC_FURNITURE_RE.search(line):
        return True
    if line.lower().rstrip(".") in _LOOKAHEAD_LABEL_BLOCKLIST:
        return True
    if OTHER_FIELD_LABEL_RE.match(line) or PURE_NUMBER_LINE_RE.match(line):
        return True
    if ADDRESS_LINE_RE.search(line):
        return True
    return any(re.search(k, line, re.IGNORECASE) for k in BUYER_KEYWORDS)


def _nearest_entity_name(lines, label_idx, seller_name, max_distance=25):
    """Find the line that reads like an entity name closest to the buyer
    label — searching the WHOLE document, not just forward from the label.

    Line order is the weakest thing about OCR on a boxed layout: Google
    Vision groups the page into blocks and can emit a box's label run and
    its value run in either order, with unrelated header text in between.
    Two rounds of fixing the forward scan kept losing to whatever the next
    reordering was, so the name is located by what it LOOKS like and how
    close it is to the label instead. Lines after the label still win ties
    over lines before it, which is the normal reading order."""
    best = None
    for j, raw in enumerate(lines):
        if j == label_idx or abs(j - label_idx) > max_distance:
            continue
        if _skip_as_buyer_candidate(raw):
            continue
        cand = _clean_buyer_value(raw)
        if not _is_plausible_buyer_name(cand) or _is_seller_name(cand, seller_name):
            continue
        if not BUYER_ENTITY_HINT_RE.search(cand):
            continue
        dist = j - label_idx
        rank = (0, dist) if dist > 0 else (1, -dist)  # after the label first
        if best is None or rank < best[0]:
            best = (rank, cand)
    return best[1] if best else None


def extract_buyer_name(text, seller_name=None):
    lines = normalize_thai_text(text or "").splitlines()
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
            if (not prev_is_label and _looks_like_value_line(prev) and re.search(r"[ก-๙]", prev)
                    and not DOC_FURNITURE_RE.search(prev) and not _is_seller_name(prev, seller_name)):
                return prev

    # Forward search, keyword by keyword in priority order (same ordering
    # rationale as _find_after_keyword). Done here rather than through
    # _find_after_keyword because a name needs validating — that helper's
    # generic "first regex match wins" would return a table cell like "1".
    for kw in BUYER_KEYWORDS:
        for i, line in enumerate(lines):
            if TABLE_HEADER_LINE_RE.search(line):
                continue
            m = re.search(kw, line, re.IGNORECASE)
            if not m:
                continue
            # An English sub-label right after the keyword ("Customer Code",
            # "ลูกค้า No.") means this is a code field, not the name field.
            if re.match(r"\s*(?:Code|No\.?|ID|Number)\b", line[m.end():], re.IGNORECASE):
                continue
            # Label and value on one line — unambiguous, take it.
            cand = _clean_buyer_value(line[m.end():])
            if _is_plausible_buyer_name(cand) and not _is_seller_name(cand, seller_name):
                return cand
            # Otherwise scan the lines below. Non-value lines are skipped
            # for free (see _skip_as_buyer_candidate) because a column-major
            # OCR read stacks a whole run of labels and header text between
            # a label and its value; only lines that could plausibly have
            # BEEN the value spend the budget. Among what's left, a line
            # that reads like an entity name wins over one that merely has
            # letters in it — the first text line after the label is often
            # stray page furniture, not the buyer.
            fallback = None
            budget = 4
            for j in range(1, 12):
                if i + j >= len(lines):
                    break
                nxt = lines[i + j]
                if _skip_as_buyer_candidate(nxt):
                    continue
                cand = _clean_buyer_value(nxt)
                if (not _is_plausible_buyer_name(cand)) or _is_seller_name(cand, seller_name):
                    budget -= 1
                    if budget <= 0:
                        break
                    continue
                if BUYER_ENTITY_HINT_RE.search(cand):
                    return cand
                if fallback is None:
                    fallback = cand
                budget -= 1
                if budget <= 0:
                    break
            # Nothing that reads like a name in the lines just below the
            # label — widen to the nearest entity-looking line anywhere
            # around it before settling for the forward scan's best guess.
            near = _nearest_entity_name(lines, i, seller_name)
            if near:
                return near
            if fallback:
                return fallback
    return None


VAT_RATE = 0.07

# Tolerances for checking the three amounts against each other: a couple
# of satang for rounding on the sum, and a little slack on the rate because
# a real invoice's VAT is rounded to satang before being printed.
_AMOUNT_TOL = 0.02
_RATE_TOL = 0.0015


def _amounts_balance(subtotal, vat, total):
    """ยอดก่อนภาษี + VAT = ยอดรวม"""
    if subtotal is None or vat is None or total is None:
        return False
    return abs((subtotal + vat) - total) <= max(_AMOUNT_TOL, abs(total) * 0.0005)


def _vat_rate_ok(subtotal, vat):
    """VAT เป็น 7% ของยอดก่อนภาษี (หรือเป็นศูนย์ทั้งคู่)"""
    if subtotal is None or vat is None:
        return False
    if subtotal <= 0:
        return vat == 0
    return abs(vat / subtotal - VAT_RATE) <= _RATE_TOL


def _fmt_baht(n):
    """2,571.03 / 140 — show satang only when there are any."""
    if n is None:
        return "—"
    s = f"{round(n, 2):,.2f}"
    return s[:-3] if s.endswith(".00") else s


def totals_mismatch_reason(subtotal, vat, total):
    """The warning shown when the three amounts contradict each other, with
    the actual figures in it so the user can see what to fix without
    reopening the document. Returns None when they agree (or when there
    isn't enough to check), so a correctly-read invoice stays clean — a
    figure that reconcile_totals derived and verified is not a problem and
    must not raise a warning of its own."""
    if subtotal is not None and vat is not None and not _vat_rate_ok(subtotal, vat):
        expected = round(subtotal * VAT_RATE, 2)
        return (f"⚠️ ยอดไม่สอดคล้องกัน: VAT ที่ระบุ ({_fmt_baht(vat)} บาท) ไม่ตรงกับ 7% "
                f"ของยอดก่อนภาษี (ควรเป็น {_fmt_baht(expected)} บาท) — โปรดตรวจสอบ")
    if None not in (subtotal, vat, total) and not _amounts_balance(subtotal, vat, total):
        return (f"⚠️ ยอดไม่สอดคล้องกัน: ยอดก่อนภาษี + VAT ({_fmt_baht(subtotal + vat)} บาท) "
                f"ไม่เท่ากับยอดรวม ({_fmt_baht(total)} บาท) — โปรดตรวจสอบ")
    return None


def reconcile_totals(subtotal, vat, total):
    """Cross-check ยอดก่อนภาษี / VAT / ยอดรวม against each other and repair
    one of them when the other two agree.

    The three amounts on a tax invoice are not independent — subtotal + VAT
    = total, and VAT is 7% of the subtotal — but each was being extracted by
    its own keyword search with no check that the results were consistent.
    A confirmed failure: a real invoice came out subtotal=2,571.03,
    VAT=2,571.03, total=39,300.00, i.e. the same number was captured twice
    (the keyword search for the subtotal landed on the VAT figure). The
    arithmetic says exactly which one is wrong: 39,300.00 − 2,571.03 =
    36,728.97, and 2,571.03 / 36,728.97 = 7.00% on the nose.

    Only rewrites a value when a candidate set both balances AND has a
    correct 7% rate, so a guess can't quietly replace what the document
    actually says. Returns (subtotal, vat, total). A set it could not
    reconcile is returned untouched — totals_mismatch_reason then turns it
    into the warning the user sees."""
    if _amounts_balance(subtotal, vat, total) and _vat_rate_ok(subtotal, vat):
        return subtotal, vat, total

    # Each candidate trusts two of the three figures and derives the third.
    candidates = []
    if vat is not None and total is not None:
        candidates.append((round(total - vat, 2), vat, total))
    if subtotal is not None and total is not None:
        candidates.append((subtotal, round(total - subtotal, 2), total))
    if subtotal is not None and vat is not None:
        candidates.append((subtotal, vat, round(subtotal + vat, 2)))

    for s, v, t in candidates:
        if _amounts_balance(s, v, t) and _vat_rate_ok(s, v):
            return s, v, t

    # Two of the three are missing, or nothing adds up — leave the figures
    # exactly as OCR read them and let the reviewer decide.
    return subtotal, vat, total


def classify_doc_type(fields):
    """เต็มรูป ต้องมีเลขผู้เสียภาษีผู้ขาย (13 หลัก) + เลขที่ใบกำกับ + ชื่อผู้ซื้อ
    ถ้าขาดอย่างใดอย่างหนึ่ง ถือเป็นใบย่อ (หัก VAT ซื้อไม่ได้). ไม่ตรวจสอบ checksum
    ของเลขผู้เสียภาษีอีกต่อไป — แค่สกัดเลขออกมาได้ครบ 13 หลักก็พอ."""
    has_marker = fields.get("_has_tax_invoice_marker")
    has_tax_id = has_valid_tax_id_format(fields.get("seller_tax_id"))
    has_invoice_no = bool(fields.get("invoice_no"))
    has_buyer = bool(fields.get("buyer_name"))
    if has_marker and has_tax_id and has_invoice_no and has_buyer:
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
    if fields.get("total") is None:
        reasons.append("ไม่พบยอดรวม")
    # A document that looks like a full ใบกำกับภาษี in every other respect
    # but has no buyer name gets classified ย่อ (VAT not deductible). That's
    # a big downgrade to make silently on one missing field, so say it out
    # loud — usually OCR just missed the name and the user can type it in.
    if fields.get("_has_tax_invoice_marker") and not fields.get("buyer_name"):
        reasons.append("ไม่พบชื่อผู้ซื้อ (ถูกจัดเป็นใบย่อ หักภาษีซื้อไม่ได้)")
    # ใบย่อ has no subtotal/VAT to check against each other by law
    if fields.get("doc_type") != "ย่อ":
        mismatch = totals_mismatch_reason(
            fields.get("subtotal"), fields.get("vat"), fields.get("total")
        )
        if mismatch:
            reasons.append(mismatch)
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

# How many non-numeric lines may sit between the totals labels and the
# totals figures before we stop believing they belong together.
_TOTALS_BLOCK_MAX_GAP = 12

# Trailing "[.,]-" is the Thai whole-baht shorthand, not a minus sign — see
# TRAILING_DASH_SATANG_RE. A totals column printed as "1,300.- / 91.- /
# 1,391.-" has to register as a run of numbers like any other.
PURE_NUMBER_LINE_RE = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?\s*(?:[.,]-)?\s*%?$")


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
        # The value run doesn't always begin where the label run ends.
        # Confirmed on a real invoice: the whole payment-method and
        # signature block ("การชำระเงิน/Payment", "เงินสด Cash", "ผู้มีอำนาจ
        # ลงนาม", a row of dots...) was emitted between the totals labels
        # and the totals figures, eight lines of it, so requiring the
        # numbers to start immediately found nothing at all. Skip over
        # non-numeric lines to reach the figures, but stop at another
        # totals label — those numbers would belong to it, not to us.
        k = j
        gap = 0
        while k < n and not (lines[k] and PURE_NUMBER_LINE_RE.match(lines[k])):
            if lines[k] and _classify_totals_label(lines[k]) is not None:
                break
            gap += 1
            if gap > _TOTALS_BLOCK_MAX_GAP:
                break
            k += 1
        values = []
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
    # seller_name is passed in so the buyer search can rule it out — see
    # _is_seller_name
    buyer_name = extract_buyer_name(text, seller_name=seller_name)

    doc_info_block = _extract_doc_info_block(text)
    invoice_no = doc_info_block.get("doc_no") or extract_invoice_no(text)

    totals_block = _extract_totals_block(text)
    subtotal = (_clean_number(totals_block["subtotal"]) if "subtotal" in totals_block
                else _clean_number(_find_after_keyword(text, SUBTOTAL_KEYWORDS)))
    vat = (_clean_number(totals_block["vat"]) if "vat" in totals_block
           else _clean_number(_find_after_keyword(text, VAT_KEYWORDS)))
    total = (_clean_number(totals_block["total"]) if "total" in totals_block
             else _clean_number(_find_after_keyword(text, TOTAL_KEYWORDS)))

    # Two fields resolving to the exact same figure means one keyword search
    # ran past its own value and landed on the next field's — the signature
    # of a value printed above its label. Try reading it from above before
    # falling back on arithmetic.
    if subtotal is not None and subtotal == vat:
        recovered = _find_number_above_keyword(text, SUBTOTAL_KEYWORDS, exclude=(vat, total))
        if recovered is not None:
            subtotal = recovered

    # The three amounts are extracted independently above, each by its own
    # keyword search — cross-check them against each other before they get
    # recorded. See reconcile_totals.
    subtotal, vat, total = reconcile_totals(subtotal, vat, total)

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

    # ใบกำกับภาษีอย่างย่อ (ม.86/6) แสดงได้เฉพาะยอดรวมที่รวม VAT แล้วเท่านั้น
    # ห้ามแยกยอดก่อนภาษี/VAT ตามกฎหมาย ถ้า regex จับตัวเลขมาผิด ๆ ได้ (เช่น
    # หลุดมาจากตารางรายการสินค้า หรือบรรทัดที่ไม่เกี่ยวข้อง) ก็ต้องทิ้งไป
    # ไม่ใช่ค่าที่ควรมีอยู่จริงบนเอกสารประเภทนี้
    if fields["doc_type"] == "ย่อ":
        fields["subtotal"] = None
        fields["vat"] = None

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
