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
import itertools

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
    text = text.replace("ํา", "ำ")
    # SARA AM followed by SARA AA is not a legal Thai sequence — SARA AM
    # already closes the syllable — so "ำา" is always OCR doubling the
    # vowel. It shows up constantly ("ยอดชำาระสุทธิ", "วันครบกำาหนด",
    # "ตำาบล", "ชำาระโดย") and breaks every keyword containing it.
    return text.replace("ำา", "ำ")

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

# "เลขที่?" — the MAI EK is optional for the same reason as in
# TOTAL_KEYWORDS: OCR drops it. A real invoice's number label came through
# as "เลขที / NO".
# The lookahead on the bare "เลขที่?" excludes the OTHER numbers a Thai
# invoice labels the same way — a bank account ("เลขที่บัญชี"), a reference
# ("เลขที่อ้างอิง"), a purchase order ("เลขที่ใบสั่งซื้อ"). Confirmed live: an
# invoice recorded the seller's bank account number as its invoice number.
# The tone mark is inside the lookahead too, so the optional-ก่อน-mark form
# can't sidestep it by matching one character less.
INVOICE_NO_KEYWORDS = [
    r"เลขที่ใบกำกับภาษี", r"เลขที่เอกสาร", r"เลขที่ใบเสร็จ",
    # "(?<!เดิม)" — a reissued receipt names the document it REPLACES:
    # "เป็นการยกเลิกและออกใบกำกับภาษีฉบับใหม่ แทนฉบับเดิมเลขที่ 041030406649".
    # Confirmed live on a Makro receipt: that cancelled number was filed as
    # this receipt's own.
    r"(?<!เดิม)เลขที่?(?![่]?(?:บัญชี|อ้างอิง|ใบสั่งซื้อ|ผู้เสีย|ประจำตัว|สมาชิก))",
    r"Invoice\s*No\.?", r"Tax\s*Invoice\s*No\.?", r"Document\s*No\.?", r"No\.",
    # บิลเงินสดเล่มกระดาษพิมพ์เลขที่เล่มด้วยเครื่องหมาย numero "№" ซึ่ง OCR
    # อ่านเป็น "Ne" เกือบทุกครั้ง (ยืนยันจากใบ หจก.ภควดีปิโตรเลียม:
    # "Ne 11143" คือเลขที่ 11143) บังคับให้เป็นคำเดี่ยว ไม่ใช่ส่วนของคำอังกฤษ
    r"№", r"(?<![A-Za-z])N[eo°](?![A-Za-z])",
]
DATE_KEYWORDS = [r"วันที่", r"Date"]

# Tried before the generic "วันที่"/"Date". An invoice prints several dates
# — the issue date, the due date, the PO date — and a column-major OCR read
# can put any of them first. Confirmed live: an invoice issued 15/09/2026
# was filed as 2026-10-15, its credit-30-days due date, because
# "วันที่ครบกำหนดชำระ" was read out before "วันที่ออกใบกำกับภาษี".
ISSUE_DATE_KEYWORDS = [
    r"วันที่ออกใบกำกับภาษี", r"วันที่ออกใบเสร็จ", r"วันที่ออกเอกสาร",
    r"วันที่ใบกำกับภาษี", r"วันที่เอกสาร",
    r"Tax\s*Invoice\s*Date", r"Invoice\s*Date", r"Date\s*of\s*Issue",
    r"Issue\s*Date",
]

# Dates that belong to some OTHER field. The Thai labels run ON from the
# keyword ("วันที่" + "ครบกำหนดชำระ"); the English ones run BEFORE it ("Due"
# + "Date"), so each side is checked against its own pattern, anchored to
# the match so a second label further along the same line can't trip it.
_OTHER_DATE_SUFFIX_RE = re.compile(
    r"\s*(?:ครบกำหนด|กำหนดชำระ|นัดชำระ|สั่งซื้อ|รับสินค้า|ส่งสินค้า|หมดอายุ)"
)
_OTHER_DATE_PREFIX_RE = re.compile(
    r"(?:Due|Payment|Delivery|Received|Order|Expiry|Ship(?:ping)?)\s*$",
    re.IGNORECASE,
)


def _is_other_field_date(text, m):
    """True when the date keyword matched at `m` labels a date other than
    the document's own — a due date, a PO date, a delivery date."""
    if _OTHER_DATE_SUFFIX_RE.match(text, m.end()):
        return True
    return bool(_OTHER_DATE_PREFIX_RE.search(text[max(0, m.start() - 24):m.start()]))

# Matches dd/mm/yyyy AND yyyy/mm/dd. The leading group allows four digits
# so a year-first date is captured whole: against the old \d{1,2} opener,
# "2025/02/18" matched starting from its third character, giving "25/02/18"
# — filed as 25 February 2018.
# The spaces are horizontal only, never \s: a date is printed on one line,
# and letting the gaps swallow newlines would splice three numbers stacked
# in a column into a date that was never on the page. Confirmed live: an
# invoice dated "25 /08/ 2025" — OCR put a space either side of each slash
# — matched nothing at all and was filed with no date.
DATE_TOKEN_RE = re.compile(r"\d{1,4}[ \t]*[/.\-][ \t]*\d{1,2}[ \t]*[/.\-][ \t]*\d{1,4}")
# The lookbehinds keep "ภาษีมูลค่าเพิ่ม" from matching the two goods-total
# lines that merely mention VAT — "สินค้าที่เสียภาษีมูลค่าเพิ่ม" (the pre-tax
# subtotal) and "สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม" (exempt goods). Reading
# either as the VAT amount puts the wrong figure in the VAT box.
# "(?:ภา)?" — OCR clipped the first syllable off a real invoice's VAT line
# ("ษีมูลค่าเพิ่ม 7%"), leaving no VAT amount at all. The exclusions are
# repeated with that syllable attached so the shorter match can't sneak
# past them by starting one syllable later.
# The real anchor is "มูลค่าเพิ่ม"; everything before it is whatever OCR made
# of "ภาษี" — seen as "ภาษี", "ษี" (first syllable clipped) and "ภาพ" (ษี
# misread) on real invoices. Each exclusion is repeated with every prefix
# length so a shorter match can't start past the lookbehind and sneak in.
# "(?<!ที่รวม...)" — ป้ายชุดเดียวกันมีบรรทัดที่สามคือ "มูลค่าสินค้าที่รวม
# ภาษีมูลค่าเพิ่ม" ซึ่งคือยอดรวมที่รวม VAT แล้ว ไม่ใช่ตัว VAT ยืนยันจากใบ
# B2S: บรรทัดนั้นคือ 52.00 ส่วน VAT จริงคือ 3.40
VAT_KEYWORDS = [
    r"(?<!ที่เสีย)(?<!ยกเว้น)(?<!ที่รวม)"
    r"(?<!ที่เสียภา)(?<!ยกเว้นภา)(?<!ที่รวมภา)"
    r"(?<!ที่เสียภาษี)(?<!ยกเว้นภาษี)(?<!ที่รวมภาษี)"
    r"(?:ภาษี|ภาพ|ภา|ษี)?มูลค่าเพิ่ม",
    r"VAT", r"Vat",
]
# Most specific / least ambiguous first. "จำนวนเงิน" (bare, no suffix) is
# deliberately last/lowest-priority — it's also part of the line-items
# table's column header wording on some invoices ("...ราคา/หน่วย ส่วนลด
# จำนวนเงินรวม"), so more specific labels should win when present. It's
# still needed because some receipts literally label the pre-tax subtotal
# just "จำนวนเงิน" / "SUB TOTAL".
SUBTOTAL_KEYWORDS = [
    r"มูลค่าหลังส่วนลด", r"จำนวนเงินหลังหักส่วนลด", r"หลังหักส่วนลด",
    r"ยอดก่อนภาษี", r"มูลค่าก่อนภาษี",
    # "มูลค่าสินค้า" เฉย ๆ ตรงกับบรรทัดพี่น้องของมันเองสองบรรทัดที่ไม่ใช่
    # ยอดก่อนภาษี และอยู่เหนือมันบนกระดาษ จึงถูกหยิบไปก่อน ยืนยันจากใบ B2S
    # ที่พิมพ์ครบทั้งสามบรรทัด:
    #     มูลค่าสินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม   0.00   <- ของที่ไม่เสีย VAT
    #     มูลค่าสินค้าที่รวมภาษีมูลค่าเพิ่ม    52.00   <- ยอดรวมที่รวม VAT แล้ว
    #     มูลค่าสินค้าที่เสียภาษีมูลค่าเพิ่ม   48.60   <- ยอดก่อนภาษีตัวจริง
    # เดิมจะได้ 0.00 มาเป็นยอดก่อนภาษี
    r"มูลค่าสินค้า(?!(?:ที่)?(?:ยกเว้น|ไม่เสีย)|ที่รวมภาษี)",
    r"ราคารวมสินค้า", r"รวมราคาสินค้า",
    # A bare "ราคารวม" is the goods total BEFORE VAT — the invoice prints
    # it above its own "ภาษีมูลค่าเพิ่ม" and "รวมทั้งสิ้น" lines. Confirmed
    # live: the label was recognised by nothing at all, so ยอดก่อนภาษี came
    # back empty and ยอดรวม took the VAT figure. The same words head the
    # last column of the items table, which is why "ราคารวม" is a column
    # heading too — see COLUMN_HEADER_WORD_RE. The lookahead keeps it off
    # "ราคารวมทั้งสิ้น", which is the GRAND total, the same trap "รวมเงิน"
    # below is guarded against.
    r"ราคารวม(?!ทั้งสิ้?น|สุทธิ)",
    # An invoice that carries both VATable and VAT-exempt goods states the
    # VATable base on its own line ("สินค้าที่เสียภาษีมูลค่าเพิ่ม") — that IS
    # the pre-tax subtotal. It has to be matched ahead of VAT_KEYWORDS,
    # which its own wording also matches.
    r"สินค้าที่เสียภาษีมูลค่าเพิ่ม", r"ที่เสียภาษีมูลค่าเพิ่ม",
    # "มูลค่าสินค้า/บริการ" — matched loosely on "สินค้า...บริการ" because OCR
    # mangles the front of it ("ทุกคาสินค้าบริการ" on a real invoice).
    r"สินค้า\s*[/\s]?\s*บริการ",
    # "รวมเงิน" must not swallow "รวมเงินทั้งสิ้น", which is the GRAND total —
    # a real invoice had its total recorded as the pre-tax subtotal because
    # this keyword matched that line first.
    r"รวมเป็นเงิน", r"รวมเงิน(?!ทั้งสิ้?น|รวม|สุทธิ)",
    r"After\s*Discount", r"Sub\s*Total", r"จำนวนเงิน",
]
# "สิ้?น" — the MAI THO on สิ้น is optional on purpose. Confirmed on a real
# invoice: Vision dropped the tone mark and read the grand-total label as
# "ราคารวมทั้งสิน", which matched no keyword at all, so the totals block
# failed to pair up and the amounts came out of unrelated table cells.
# Thai tone marks are small and the first thing a scan loses.
TOTAL_KEYWORDS = [
    # "มูลค่าสินค้าที่รวมภาษีมูลค่าเพิ่ม" แปลว่ายอดที่รวม VAT แล้ว ซึ่งก็คือ
    # ยอดรวมตามนิยาม ไม่ต้องตีความ ใบ B2S ใช้ป้ายนี้แทน "รวมทั้งสิ้น"
    r"(?:มูลค่า)?สินค้าที่รวมภาษีมูลค่าเพิ่ม",
    r"จำนวนเงิน(?:รวม)?ทั้งสิ้?น", r"จำนวนเงินรวมสุทธิ", r"รวมมูลค่าสุทธิ", r"มูลค่าสุทธิ",
    # "รวมทั้งสิ้น" with an optional word in the middle — invoices write
    # "รวมเงินทั้งสิ้น", "รวมมูลค่าทั้งสิ้น", "รวมราคาทั้งสิ้น" for the same thing.
    r"รวม(?:เงิน|มูลค่า|ราคา|จำนวนเงิน)?ทั้งสิ้?น", r"ยอดชำระ(?:สุทธิ|เงิน)?",
    r"ยอดสุทธิ", r"ยอดรวมสุทธิ", r"ยอดรวม",
    r"Grand\s*Total", r"Total\s*Amount", r"Total",
]
# "ลูกค้า" carries two negative lookbehinds so it matches the buyer-name
# label ("ชื่อลูกค้า") but NOT a customer *code* field ("รหัสลูกค้า",
# "เลขที่ลูกค้า") — those hold a short numeric/alphanumeric code, which the
# forward search would otherwise happily return as the buyer's name.
BUYER_KEYWORDS = [
    r"นามผู้ซื้อ", r"ชื่อผู้ซื้อ", r"ข้อมูลผู้ซื้อ", r"รายละเอียดผู้ซื้อ",
    r"(?<!รหัส)(?<!เลขที่)ลูกค้า", r"Customer", r"Bill\s*To", r"Buyer",
    # Bare "ผู้ซื้อ" last: it also occurs in the terms printed at the foot
    # of an invoice ("...แม้จะส่งมอบแก่ผู้ซื้อแล้ว..."), which the
    # prose-length guard in extract_buyer_name keeps out.
    r"(?<!รหัส)ผู้ซื้อ",
    # ป้ายผู้ซื้อที่สั้นที่สุดเท่าที่เจอบนใบจริง: ใบ B2S เขียนกล่องลูกค้าว่า
    # "ชื่อ" กับ "ที่อยู่" เท่านั้น ไม่มีคำว่าผู้ซื้อ/ลูกค้า/Customer เลย
    # ผลคือชื่อผู้ซื้อว่าง ซึ่งลากให้ทั้งใบถูกจัดเป็นใบย่อ แล้วยอดก่อนภาษี
    # กับ VAT ถูกล้างทิ้งตาม ม.86/6 ทั้งที่บนกระดาษพิมพ์ 48.60 กับ 3.40 ชัด
    #
    # ใส่ตรง ๆ ไม่ได้เพราะ "ชื่อ" เป็นคำตั้งต้นของป้ายอื่นเต็มไปหมด จึง
    # บังคับให้อยู่ต้นบรรทัด และกันคำที่ทำให้มันเป็นชื่อของอย่างอื่น
    # สังเกตว่ากันเฉพาะตอนเขียนติดกัน ("ชื่อบริษัท") ส่วน "ชื่อ บริษัท
    # นำโชค จำกัด" ที่เว้นวรรคยังผ่าน เพราะนั่นคือชื่อผู้ซื้อจริง ๆ
    # อยู่ท้ายสุดของรายการ ป้ายที่เจาะจงกว่าจึงชนะเสมอถ้ามี
    r"^\s*ชื่อ(?!\S*(?:สินค้า|บริษัท|ร้าน|ผู้ขาย|ผู้รับ|ผู้จัดทำ|บัญชี|ธนาคาร|"
    r"พนักงาน|สมาชิก|ย่อ|เต็ม|เรื่อง|ไฟล์|งาน))",
    # "นาม" เปล่า ๆ เป็นป้ายผู้ซื้อบนบิลเงินสดเล่มกระดาษ ("นาม.........")
    # กันคำที่ขึ้นต้นด้วยนามแต่หมายถึงอย่างอื่น
    r"^\s*นาม(?!สกุล|บัตร|แฝง|ธรรม)",
]
# NOTE: "Buyer Name" is intentionally NOT in this forward-search list — on
# a real invoice it was OCR'd sitting AFTER the buyer name value instead of
# before it, so searching forward from it grabbed unrelated text below.
# extract_buyer_name() handles that specific case separately by checking
# the line *before* "Buyer Name" first.
# What makes a document a ใบกำกับภาษี at all — so this one word decides
# whether VAT can be claimed. Two allowances, both from real documents:
#
#   - The vowel between ก and กับ is whatever OCR made of SARA AM. Seen as
#     "ใบก๋ากับภาษี" (MAI CHATTAWA + SARA AA) — that single garbled letter
#     was the only occurrence in the document, so a full tax invoice was
#     filed as ใบย่อ and its subtotal and VAT were wiped as required by
#     ม.86/6. The character class is Thai vowel signs and tone marks only.
#     (A blanket "tone mark + า -> ำ" normalisation is NOT safe: "ค่า" is a
#     real syllable, and it would corrupt "มูลค่า", "ราคา", "ค่าบริการ".)
#   - The English title, which survives Thai garbling untouched.
TAXINV_MARKER = r"ใบก[ั-๎]{0,2}กับภาษี|(?i:TAX\s*INVOICE)"
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
    # "ล่าดับ" is how OCR keeps rendering "ลำดับ" (SARA AM read as MAI EK +
    # SARA AA) — a spelling normalize_thai_text can't repair, since that
    # only merges the decomposed NIKHAHIT form.
    r"ลำดับ|ล่าดับ|รหัสสินค้า|ราคา\s*/\s*หน่วย|ราคาต่อหน่วย|รายการสินค้า|จำนวนเงินรวม(?!สุทธิ|ทั้งสิ้?น)|"
    # "จำนวนเงินรวมทั้งสิ้น (ตัวอักษร)" spells the total out in words and
    # never carries a figure — but it matches the grand-total keywords, so
    # the search that landed on it took the next number it could find,
    # which belonged to a different field two lines below.
    r"\(\s*ตัวอักษร\s*\)|\(\s*ตัวหนังสือ\s*\)|\(\s*ALPHABET\s*\)|"
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

# How far a value may run past the end of a keyword's search window before
# it is clipped — long enough for any document number or amount.
_WINDOW_OVERRUN = 40

NUM_RE = r"[-+]?\d[\d,]*(?:\.\d+)?"
TAXID_RE = re.compile(r"(\d[\s-]?\d{4}[\s-]?\d{5}[\s-]?\d{2}[\s-]?\d)")
TAXID_PLAIN_RE = re.compile(r"\b\d{13}\b")


# Thai invoices very often write a whole-baht amount as "1,300.-" (and
# sometimes "1,300,-"), where the dash stands in for the satang rather than
# being a minus sign. Confirmed on a real invoice where EVERY amount was
# printed this way, which made the extractor report no amounts at all.
TRAILING_DASH_SATANG_RE = re.compile(r"\s*[.,]-\s*$")

# A totals column often prints its currency on every line ("183,800.00
# บาท"). Confirmed live: none of those lines registered as numbers, so the
# totals box paired nothing and the amounts were scavenged from elsewhere.
CURRENCY_SUFFIX_RE = re.compile(r"\s*(?:บาท|บ\.|Baht|THB|฿)\s*$", re.IGNORECASE)

# OCR also reads the decimal point as a comma: a real invoice came through
# with "15,750,00" and "1,102,50" for 15,750.00 and 1,102.50. Stripping the
# commas as thousands separators turned those into 1,575,000 and 110,250 —
# a hundredfold error, silently recorded. A trailing group of exactly TWO
# digits after a comma can only be satang, since a thousands group is
# always three digits.
COMMA_DECIMAL_RE = re.compile(r"^([-+]?\d{1,3}(?:,\d{3})*),(\d{2})$")


# เพดานของ "จำนวนเงินที่เป็นไปได้บนใบกำกับภาษีหนึ่งใบ"
#
# ใบกำกับภาษีใบเดียวไม่มีทางถึงหนึ่งหมื่นล้านบาท แต่ตัวเลขยาว ๆ บนกระดาษมี
# เต็มไปหมด — บาร์โค้ด เลขอ้างอิง เลขผู้เสียภาษี เลขที่ใบเสร็จ POS
#
# ยืนยันจากใบจริง B2S: เลขใต้บาร์โค้ด 66202507225005110311586 ถูกเก็บเป็น
# "ยอดรวม" แล้วแสดงบนหน้าเว็บว่า 6.62025072250051e+23 ซึ่งนอกจากผิดแล้วยัง
# ทำให้ยอดทั้งใบใช้ไม่ได้เลย. ตัดที่ขนาดของตัวเลขคือกฎที่เถียงไม่ได้:
# ไม่มีการตีความไหนที่เลข 23 หลักเป็นจำนวนเงินของใบนี้
_MAX_PLAUSIBLE_AMOUNT = 1e10


def _clean_number(s):
    if s is None:
        return None
    s = CURRENCY_SUFFIX_RE.sub("", s.translate(THAI_DIGITS).strip())
    s = TRAILING_DASH_SATANG_RE.sub("", s)
    m = COMMA_DECIMAL_RE.match(s)
    if m:
        s = f"{m.group(1)}.{m.group(2)}"
    s = s.replace(",", "").strip()
    try:
        val = float(s)
    except ValueError:
        return None
    if abs(val) >= _MAX_PLAUSIBLE_AMOUNT:
        return None
    return val


# One column heading of an items table, alone on its line — what a
# column-major OCR read produces instead of one "ลำดับ รายการ จำนวน ..."
# header row. TABLE_HEADER_LINE_RE can't catch these on its own because
# several are ordinary words that also label real fields.
COLUMN_HEADER_WORD_RE = re.compile(
    r"^(?:ลำดับ(?:ที่?)?|ล่าดับ(?:ที่?)?|ที่|รหัสสินค้า|รหัส|รายการ(?:สินค้า)?(?:\s*/\s*บริการ)?|รายละเอียด|"
    r"จำนวน|จำนวนเงิน|หน่วย|ราคา(?:\s*/\s*หน่วย|ต่อหน่วย|รวม)?|ราคาสุทธิ|ส่วนลด|มูลค่า|"
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


_CURRENCY_WORD_AHEAD_RE = re.compile(r"^(?:THB|Baht|BHT)", re.IGNORECASE)


def _glued_to_letters(text, m):
    """ตัวเลขนี้เป็นชิ้นส่วนของรหัสที่ปนตัวอักษรอยู่หรือเปล่า

    "114100" ใน "QRPP 114100XXXXXX6" ไม่ใช่จำนวนเงิน แต่ NUM_RE ตัดมาให้
    ได้หน้าตาเหมือนจำนวนเงินทุกประการ สิ่งที่บอกความต่างคือตัวอักษรที่
    ติดกันโดยไม่มีช่องว่างคั่น"""
    before = text[m.start() - 1] if m.start() > 0 else ""
    after = text[m.end():m.end() + 4]
    if before.isascii() and before.isalpha():
        return True
    if after[:1].isascii() and after[:1].isalpha():
        return not _CURRENCY_WORD_AHEAD_RE.match(after)
    return False


def _best_match_on_line(rest, value_pattern, require_digit=False, max_start=None):
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
    if max_start is not None:
        # The caller is searching a window but handed us extra text past its
        # end, so a value straddling the boundary stays whole — see the
        # fallback search in _find_after_keyword. Keep matches that BEGIN
        # inside the window; they may run past it.
        matches = [mm for mm in matches if mm.start() < max_start]
    if not matches:
        return None
    if value_pattern is NUM_RE:
        filtered = [mm for mm in matches if not rest[mm.end():mm.end() + 3].strip().startswith("%")]
        # เลขที่ใหญ่เกินกว่าจะเป็นเงินต้องถูกทิ้งตั้งแต่ตรงนี้ ไม่ใช่ไปทิ้ง
        # ทีหลังตอนแปลงเป็นตัวเลข เพราะการค้นหาจะ "ใช้สิทธิ์ไปแล้ว" กับ
        # บรรทัดนั้นและไม่มองหาต่อ — ยืนยันจากใบ B2S: พอปัดเลขบาร์โค้ดทิ้ง
        # ตอนแปลง ยอดรวมกลายเป็นว่างเปล่า แทนที่จะไปเจอ 52.00 ที่อยู่ถัดไป
        filtered = [mm for mm in filtered if _clean_number(mm.group(0)) is not None]
        # ตัวเลขที่ติดอยู่กลางโค้ดตัวอักษรไม่ใช่จำนวนเงิน — มันเป็นชิ้นส่วน
        # ของรหัสอ้างอิง ยืนยันจากใบ B2S: บรรทัดวิธีชำระเงินคือ
        # "QRPP 114100XXXXXX6" (เลขบัตรที่ถูกปิดบางส่วน) แล้ว 114100 ถูก
        # เก็บเป็น VAT ของใบ 52 บาท. เช็คเฉพาะตัวอักษรอังกฤษ เพราะคำไทย
        # ที่ติดตัวเลขเป็นหน่วยเงินปกติ ("52.00บาท")
        filtered = [mm for mm in filtered if not _glued_to_letters(rest, mm)]
        if not filtered:
            return None
        return filtered[-1].group(0).strip()
    if require_digit:
        matches = [mm for mm in matches if re.search(r"\d", mm.group(0))]
        if not matches:
            return None
    return matches[0].group(0).strip()


# ใบที่ออกแทนใบเดิมจะประกาศเลขที่ของ "ใบที่ถูกยกเลิก" ไว้บนหัวกระดาษ และ
# ประกาศนั้นมีทั้งเลขที่และวันที่ของใบเก่า ซึ่งไม่ใช่ของใบที่ถืออยู่
#
# เดิมกันไว้ด้วย lookbehind "(?<!เดิม)เลขที่" ซึ่งพอดีกับสำนวนของ Makro
# ("แทนฉบับเดิมเลขที่ 041030406649") แต่ไม่ครอบคลุมสำนวนอื่น ใบจริงของ B2S
# เขียนว่า "เป็นการยกเลิกใบกำกับภาษีอย่างย่อเลขที่ 103-107827 วันที่ 22
# กรกฎาคม 2568 และออกใบกำกับภาษีมีอิเล็กทรอนิกส์ใหม่แทน" — ไม่มีคำว่า
# "เดิม" ติดกับ "เลขที่" เลย การ์ดเดิมจึงไม่ทำงาน
#
# กันที่ต้นเหตุแทน: สิ่งที่ทำให้เลขนั้นใช้ไม่ได้คือ "ประโยคนี้พูดถึงการ
# ยกเลิก" ไม่ใช่รูปประโยคแบบใดแบบหนึ่ง จึงดูว่าก่อนถึงคำค้นมีคำว่ายกเลิก
# หรือไม่ ใช้ได้กับทุกฟิลด์ที่ค้นด้วยคำนำหน้า ไม่ใช่แค่เลขที่
_CANCELLED_DOC_RE = re.compile(
    r"ยกเลิก|แทนฉบับ|ฉบับเดิม|Cancell?ed|Replaces?\b|In\s+place\s+of",
    re.IGNORECASE,
)

# "เลขที่" ในที่อยู่ไปรษณีย์แปลว่าบ้านเลขที่ ไม่ใช่เลขที่เอกสาร
#
# ยืนยันจากใบจริง B2S: บรรทัดที่อยู่ผู้ขายคือ "เลขที่ 9 หมู่ 3 ตำบลสุเทพ
# อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50200" ซึ่งอยู่เหนือกล่องหัวเอกสาร
# การค้นไปข้างหน้าจากคำว่า "เลขที่" จึงเจอบรรทัดนี้ก่อน แล้วคืน "50200"
# — รหัสไปรษณีย์ของผู้ขาย — เป็นเลขที่ใบกำกับภาษี
#
# แยกออกจากเลขที่เอกสารได้ด้วยคำบอกเขตการปกครอง ซึ่งไม่มีทางโผล่ในบรรทัด
# เลขที่เอกสาร บังคับให้เจออย่างน้อยสองคำ เพราะคำเดียวอาจบังเอิญได้ เช่น
# "จ." ที่เป็นตัวย่ออย่างอื่น สองคำขึ้นไปแทบเป็นไปไม่ได้ที่จะบังเอิญ
_ADDRESS_WORD_RE = re.compile(
    r"หมู่ที่|หมู่|ถนน|ซอย|ตำบล|แขวง|อำเภอ|เขต|จังหวัด|(?<![ก-ฮ])[ตอจถซ]\.(?=\s*[ก-ฮ])"
)


def _looks_like_address(fragment):
    return len(_ADDRESS_WORD_RE.findall(fragment)) >= 2


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
            # ประโยคยกเลิกพูดถึงเอกสาร "ฉบับอื่น" ไม่ใช่ฉบับนี้ — ทั้งเลขที่
            # และวันที่ในประโยคนั้นเป็นของใบที่ถูกยกเลิกไปแล้ว ยื่น ภ.พ.30
            # ด้วยเลขนั้นคือยื่นผิดใบ ดู _CANCELLED_DOC_RE
            if _CANCELLED_DOC_RE.search(line[:m.start()]):
                continue
            rest = line[m.end():]
            # บรรทัดที่อยู่: "เลขที่" ที่นี่คือบ้านเลขที่ ดู _looks_like_address
            if _looks_like_address(rest):
                continue
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
    # Fallback: search a character window after the keyword. The slice runs
    # past the window on purpose — a value that starts inside it but ends
    # outside used to be cut in half at the boundary, and the truncated
    # remainder was returned as if it were the whole value. Confirmed live:
    # invoice IV20250504-012 sat 50 characters after its "เลขที่" label, so
    # the 60-character slice ended mid-number and the app recorded
    # "IV20250504".
    for kw in keywords:
        for m in re.finditer(kw, text, re.IGNORECASE):
            # Honour the same "this line never holds a value" rule as the
            # line-based pass above — the fallback used to ignore it and
            # could still read a figure off a table heading or an
            # amount-in-words line.
            if skip_header_lines:
                line_no = text.count("\n", 0, m.start())
                on_line = lines[line_no] if line_no < len(lines) else ""
                if (TABLE_HEADER_LINE_RE.search(on_line)
                        or _is_table_column_header(lines, line_no)):
                    continue
            window_text = text[m.end():m.end() + window + _WINDOW_OVERRUN]
            val = _best_match_on_line(window_text, value_pattern,
                                      require_digit=require_digit, max_start=window)
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


# The taxpayer ID as its own label introduces it, on the label's own line.
# A page carries several 13-digit numbers — the seller's ID, the buyer's,
# sometimes an order reference — and taking whichever comes first in a
# column-major read is a coin toss. Confirmed live: an invoice was filed
# under 0994000123456, the CUSTOMER's ID, because the seller's own ID was
# letter-spaced across its box ("0 5 0 5512345678") and matched no plain
# 13-digit run at all. Hence the single optional space between digits —
# and the run may not cross a line, or it would join two unrelated numbers
# stacked in a column.
# The anchor stops at "ผู้เสีย" and lets the gap swallow whatever OCR made
# of "ภาษีอากร". Confirmed live: an invoice printed
# "เลขประจำตัวผู้เสียกษีอากร" — the ภา of ภาษี simply dropped — so the
# seller's label matched nothing and the only ID the page yielded was the
# CUSTOMER's, from the one label that survived intact.
_TAXID_LABEL_CORE = (
    r"(?:เลขประจำตัวผู้เสีย|เลขผู้เสีย|Tax\s*(?:ID|Identification))"
)

TAXID_LABELLED_RE = re.compile(
    _TAXID_LABEL_CORE + r"[^\d\n]{0,20}((?:\d[ \t\-]?){12}\d)",
    re.IGNORECASE,
)

TAXID_LABEL_RE = re.compile(
    _TAXID_LABEL_CORE + r"[^\d\n]{0,20}(\d[\d\s-]{8,18}\d)",
    re.IGNORECASE,
)


# How many lines a customer box may run to. Generous enough for a heading,
# a name, a three-line address and a taxpayer ID.
_BUYER_BLOCK_MAX_SPAN = 10


def _buyer_block_lines(lines):
    """The line numbers that fall inside a customer box.

    A box opens at a buyer label and runs until the NEXT party is named.
    The first company name after the label is the customer's own, so it
    does not end the box — the second one does. Confirmed live: an invoice
    printed the customer block above the letterhead, and judging each line
    by "is there a buyer label just above it, and no company name in
    between" stopped at the buyer's own name "บริษัท B จำกัด", put the
    customer's taxpayer ID outside the box and filed it as the issuer's.

    A copy designation ("ต้นฉบับสำหรับลูกค้า / Original") names the customer
    without opening a box, so it never starts one."""
    inside = set()
    for i, line in enumerate(lines):
        if DOC_FURNITURE_RE.search(line):
            continue
        if not any(re.search(k, line, re.IGNORECASE) for k in BUYER_KEYWORDS):
            continue
        named = bool(COMPANY_NAME_HINT_RE.search(line))
        for j in range(i, min(len(lines), i + _BUYER_BLOCK_MAX_SPAN)):
            if j > i and COMPANY_NAME_HINT_RE.search(lines[j]):
                if named:
                    break  # a second party is named: the box ended above
                named = True
            inside.add(j)
    return inside


def _in_buyer_block(lines, i):
    """True when line `i` is printed inside a customer box, so whatever it
    carries describes the BUYER rather than the issuer."""
    return i in _buyer_block_lines(lines)


def extract_tax_id(text):
    # A page labels two taxpayer IDs — the issuer's and the customer's —
    # and which one OCR reads out first is a matter of layout. Take the
    # labelled ID that is NOT printed inside the customer box; fall back
    # to the first one only if every match is (a column-major read can put
    # the customer box above the letterhead).
    lines = text.splitlines()
    labelled = []
    for m in TAXID_LABELLED_RE.finditer(text):
        candidate = re.sub(r"\D", "", m.group(1))
        if len(candidate) == 13:
            labelled.append((text.count("\n", 0, m.start()), candidate))
    buyer_lines = _buyer_block_lines(lines) if labelled else set()
    for idx, candidate in labelled:
        if idx not in buyer_lines:
            return candidate
    if labelled:
        return labelled[0][1]
    for m in TAXID_RE.finditer(text):
        candidate = re.sub(r"\D", "", m.group(1))
        if len(candidate) == 13:
            return candidate
    for m in TAXID_PLAIN_RE.finditer(text):
        return m.group(0)
    # No 13-digit number anywhere — fall back to whatever number the
    # document prints against its taxpayer-ID label. A real invoice came
    # through with twelve digits (OCR almost certainly dropped one from a
    # run of zeros), and returning nothing cascaded badly: no taxpayer ID
    # meant not a full tax invoice, which meant ม.86/6 wiped the subtotal
    # and VAT the document plainly showed. Reporting what is printed lets
    # build_review_reasons flag the length and the user fix one digit.
    for m in TAXID_LABEL_RE.finditer(text):
        candidate = re.sub(r"\D", "", m.group(1))
        if 10 <= len(candidate) <= 16:
            return candidate
    return None


def _invoice_no_under_title(text):
    """Last resort: the number printed directly under the document title,
    with no label at all. Confirmed live on an invoice whose header is just

        ใบกำกับภาษี/ใบเสร็จ
        RE00001

    Only a bare token containing a digit counts, so the English half of a
    bilingual title ("TAXINVOICE/RECEIPT") can't be taken for a number."""
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if not re.search(TAXINV_MARKER, line) and not re.search(RECEIPT_MARKER, line):
            continue
        for j in (i + 1, i + 2):
            if j >= len(lines) or not lines[j]:
                continue
            cand = lines[j]
            if DOC_VALUE_LINE_RE.match(cand) and re.search(r"\d", cand) and len(cand) >= 4:
                return cand
    return None


# How many lines above its label a document number may be found.
_DOC_NO_LOOKBACK = 3


def _looks_like_doc_no(line):
    """A token that could be a document number and nothing else: it holds
    a digit AND something that is not a digit, so a bare house number
    ("789") or a quantity can't qualify, and it is long enough that a page
    marker ("1/1") can't either."""
    line = line.strip()
    if len(line) < 5 or not DOC_VALUE_LINE_RE.match(line):
        return False
    if not re.search(r"\d", line) or not re.search(r"[A-Za-z\-]", line):
        return False
    if re.fullmatch(r"\d{10,}", line) or _parse_thai_date(line):
        return False
    return True


def _invoice_no_above_label(text):
    """The number printed on the line ABOVE its label.

    A boxed header is read column by column, and the value column can come
    out before the label column. Confirmed live: an invoice printed
    "INV-2026-091" then "ลูกค้า / Customer" then "เลขที่ใบกำกับภาษี", so the
    forward search ran past the label, through the customer box, and
    returned "789" — the house number of the buyer's address.

    Only considered when the label stands alone on its line: a label with
    its value beside it needs no guessing. The value is not always on the
    line immediately above — on the invoice above, the customer box's
    heading was emitted between the two — so a few label lines are stepped
    over, but anything else ends the search: a line that carries real
    content and is not the number means we have left the header box."""
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if i == 0 or re.search(r"\d", line):
            continue
        if not any(re.search(kw, line) for kw in INVOICE_NO_KEYWORDS):
            continue
        for j in range(i - 1, max(-1, i - 1 - _DOC_NO_LOOKBACK), -1):
            prev = lines[j]
            if _looks_like_doc_no(prev):
                return prev
            if prev and not _is_field_label_line(prev) and not DOC_FURNITURE_RE.search(prev):
                break
    return None


def extract_invoice_no(text):
    val = _find_after_keyword(
        text, INVOICE_NO_KEYWORDS, value_pattern=r"[A-Za-z0-9\-/]{3,}", require_digit=True
    )
    # A value the forward search had to wander to is worth less than one
    # sitting right above the label, so an above-the-label number wins
    # unless the forward search found a proper document number too.
    if val is None or not _looks_like_doc_no(val):
        above = _invoice_no_above_label(text)
        if above:
            return above
    return val or _invoice_no_under_title(text)


def _date_token_stands_alone(text, m):
    """วันที่ที่ถูกต้องต้องไม่ใช่ชิ้นส่วนที่ตัดออกมาจากตัวเลขยาวกว่า

    ยืนยันจากใบจริงของ หจก.ภควดีปิโตรเลียม: เลขผู้เสียภาษีของผู้ซื้อพิมพ์
    เป็น "1-1111-11111-11-1" ซึ่งข้างในมี "1111-11-1" ซ่อนอยู่ แปลงแล้วได้
    วันที่ 1111-11-01 ซึ่งเป็นวันที่ที่ใช้ได้จริงตามปฏิทิน ระบบจึงรับไว้
    แล้วบันทึกเป็นวันที่ของใบกำกับ

    เช็คแค่ตัวติดกันซ้ายขวา: วันที่จริงมีช่องว่าง ตัวอักษร หรือหัวบรรทัด
    ขนาบอยู่เสมอ ไม่เคยมีเลขหรือขีดติดหน้าติดหลัง"""
    glue = "-0123456789"
    before = text[m.start() - 1] if m.start() > 0 else " "
    after = text[m.end()] if m.end() < len(text) else " "
    return before not in glue and after not in glue


def _parse_thai_date(raw):
    """Try to parse a Thai-formatted date string into ISO yyyy-mm-dd.
    Handles dd/mm/yyyy (พ.ศ. or ค.ศ.) and 'dd เดือน ปี' formats."""
    raw = raw.translate(THAI_DIGITS).strip()

    # Year first (2025/02/18, or 2568/02/18 in พ.ศ.) — checked before the
    # day-first form, which a four-digit year can't be mistaken for.
    m = re.match(r"(\d{4})[ \t]*[/.\-][ \t]*(\d{1,2})[ \t]*[/.\-][ \t]*(\d{1,2})\s*$", raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y > 2400:
            y -= 543
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            return None

    m = re.match(r"(\d{1,2})[ \t]*[/.\-][ \t]*(\d{1,2})[ \t]*[/.\-][ \t]*(\d{2,4})", raw)
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


# The signature block at the foot of an invoice has its own "วันที่ ____"
# next to each signer, and those dates are not the document's date.
# Confirmed live: an invoice was filed under 21/01/2558, the date the buyer
# signed for the goods, instead of its own 31/01/2568.
SIGNATURE_CONTEXT_RE = re.compile(
    r"ผู้สั่งซื้อ|ผู้อนุมัติ|ผู้รับ|ผู้ส่ง|ผู้จ่าย|ผู้ตรวจ|ผู้มีอำนาจ|ลงนาม|ลายเซ็น|ลายมือชื่อ|"
    r"Authori[sz]ed|Signature|Approved|Received|Delivered"
)


def _in_signature_block(text, pos, lookback=2):
    """True when the keyword at `pos` sits in the signature block — judged
    by the line it's on and the couple of lines above it."""
    head = text[:pos].splitlines()
    tail = text[pos:].splitlines()
    around = head[-(lookback + 1):] + tail[:1]
    return any(SIGNATURE_CONTEXT_RE.search(l) for l in around)


# A "วันที่" inside a long line is part of a sentence — the terms and
# conditions at the foot of the page talk about payment deadlines, holiday
# closures and return windows, and the dates in them are not the
# document's date. Field labels are short.
_PROSE_LINE_MIN_LEN = 80


def _in_prose_line(text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    line = text[line_start:line_end if line_end != -1 else len(text)]
    return len(line.strip()) > _PROSE_LINE_MIN_LEN


def extract_date(text):
    for keywords in (ISSUE_DATE_KEYWORDS, DATE_KEYWORDS):
        for kw in keywords:
            for m in re.finditer(kw, text, re.IGNORECASE):
                if _in_signature_block(text, m.start()) or _in_prose_line(text, m.start()):
                    continue
                if _is_other_field_date(text, m):
                    continue
                # Window needs to be wide enough to skip past an intervening
                # bilingual English sub-label (e.g. "วันที่เอกสาร\nDocument
                # Date\n02/08/2025") without truncating the date itself.
                window_text = text[m.end():m.end() + 60]
                dm = DATE_TOKEN_RE.search(window_text)
                if dm:
                    iso = _parse_thai_date(dm.group(0))
                    return dm.group(0), iso
                for name in THAI_MONTHS:
                    dm2 = re.search(r"\d{1,2}\s*" + re.escape(name) + r"\s*\d{4}", window_text)
                    if dm2:
                        iso = _parse_thai_date(dm2.group(0))
                        return dm2.group(0), iso
    # Fallback: any date-looking token in the whole document — but only one
    # that actually resolves to a real calendar date. A phone number or a
    # bank account can match the shape ("456-7-89012-3" yields "56-7-8901")
    # and used to be returned as the date, unparsed, purely for being first.
    for dm in DATE_TOKEN_RE.finditer(text):
        if not _date_token_stands_alone(text, dm):
            continue
        iso = _parse_thai_date(dm.group(0))
        if iso:
            return dm.group(0), iso
    dm = DATE_TOKEN_RE.search(text)
    if dm and _date_token_stands_alone(text, dm):
        return dm.group(0), _parse_thai_date(dm.group(0))
    return None, None


# Case-insensitive: a letterhead's English name is normally set in capitals
# ("FARM NGERN FARM THONG CO., LTD."), which the case-sensitive pattern did
# not recognise as a company name at all.
# "หจก." คือคำย่อของห้างหุ้นส่วนจำกัด และร้านค้าน้ำมัน/อะไหล่จำนวนมากพิมพ์
# หัวกระดาษด้วยคำย่อล้วน ๆ ไม่มีคำว่าบริษัทหรือจำกัดเลยสักคำ
#
# ยืนยันจากใบจริงของ หจก.ภควดีปิโตรเลียม: หัวกระดาษคือ
# "(Esso) หจก.ภควดีปิโตรเลียม (สำนักงานใหญ่)" ซึ่งไม่เข้าเงื่อนไขนี้เลย
# ผู้ขายจึงไม่เคยถูกพิจารณา แล้วชื่อ "บริษัท นำโชค จำกัด" ของผู้ซื้อชนะ
# ไปโดยปริยาย — ผลคือผู้ขายกับผู้ซื้อสลับกัน และช่องผู้ซื้อว่าง
COMPANY_NAME_HINT_RE = re.compile(
    r"บริษัท|ห้างหุ้นส่วน|หจก\.?|บจก\.?|บมจ\.?|จำกัด|มหาชน|"
    r"Co\.,?\s*Ltd|Company|Corp|Public\s*Co",
    re.IGNORECASE,
)


def _is_field_label_line(line):
    """A line that is nothing but a field's label — "ชื่อลูกค้า", "Customer
    Name", "Tax Identification", a table heading. Never anybody's name."""
    line = line.strip()
    if not line:
        return True
    if line.lower().rstrip(".") in _LOOKAHEAD_LABEL_BLOCKLIST:
        return True
    if OTHER_FIELD_LABEL_RE.match(line) or COLUMN_HEADER_WORD_RE.match(line):
        return True
    if TABLE_HEADER_LINE_RE.search(line):
        return True
    return any(re.search(k, line, re.IGNORECASE) for k in BUYER_KEYWORDS)


# How far down to look for the seller's letterhead. Confirmed live: an
# invoice was OCR'd with its entire label column first — "ชื่อลูกค้า",
# "Customer Name", "ที่อยู่", ... twelve lines of it — before the letterhead,
# so an eight-line window found no company name and the old fallback
# returned the label "ชื่อลูกค้า" as the seller.
_SELLER_SEARCH_LINES = 20


# How far below a bare buyer label ("ลูกค้า / Customer") a company name is
# still that label's value.
_BUYER_LABEL_REACH = 2

# The Thai legal form a registered name opens with. A letterhead often
# prints the logo's wordmark ("BLUEMOON" / "TRADING CO., LTD.") above the
# registered name, and the wordmark's second line looks enough like a
# company to be taken for one — so a candidate carrying the Thai form wins
# over one that doesn't. Every Thai invoice seen so far files under its
# Thai name.
THAI_COMPANY_FORM_RE = re.compile(r"บริษัท|ห้างหุ้นส่วน|หจก\.?|บจก\.?|บมจ\.?")
_COMPANY_NAME_TAIL_RE = re.compile(r"จำกัด|มหาชน")


def _trim_unclosed_paren(name):
    """Cut a trailing "(" that never closes. A letterhead wraps its branch
    marker onto the next line, and OCR keeps the halves apart: confirmed
    live, a seller was recorded as "บริษัท ... จำกัด (สานักงาน" with "ใหญ่)"
    left on the line below. The registered name is complete without it."""
    if name.count("(") > name.count(")"):
        return name[:name.rindex("(")].strip()
    return name


def _merge_split_company_name(lines, i):
    """Put a registered name back together when OCR broke it in two.
    Confirmed live: "บริษัท บลูมูน เทรดดิ้ง จำกัด" came out as two lines in
    the WRONG order — "เทรดดิ้ง จำกัด" then "บริษัท บลูมูน" — so the name
    was recorded without its second half. The head is the line opening
    with the legal form and missing the "จำกัด" that closes it; the tail is
    the neighbour that carries it and opens with nothing."""
    head = lines[i]
    if not THAI_COMPANY_FORM_RE.match(head) or _COMPANY_NAME_TAIL_RE.search(head):
        return head
    for j in (i - 1, i + 1):
        if not 0 <= j < len(lines):
            continue
        tail = lines[j].strip()
        if (_COMPANY_NAME_TAIL_RE.search(tail)
                and not THAI_COMPANY_FORM_RE.match(tail)
                and not _is_latin_script(tail)
                and not re.search(r"\d", tail)
                and len(tail) <= 40):
            return f"{head} {tail}"
    return head


def _under_buyer_label(lines, i, reach=_BUYER_LABEL_REACH):
    """True when line `i` sits directly below a bare buyer label, so the
    company name on it belongs to the CUSTOMER box, not the letterhead."""
    for j in range(max(0, i - reach), i):
        if _is_bare_buyer_label(lines[j]):
            return True
    return False


def extract_seller_name(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Prefer a line that actually looks like a registered company name —
    # some invoices print a short logo/brand word (e.g. "Moshi Moshi") as
    # its own line above the real registered name ("บริษัท โมชิ โมชิ รีเทล
    # คอร์ปอเรชั่น จำกัด (มหาชน)"), and a plain "first short line" heuristic
    # grabs the logo text instead of the real name.
    # A company name standing right under "ลูกค้า / Customer" is the
    # customer's, and on a column-major read the customer box can be OCR'd
    # ahead of the letterhead. Confirmed live: an invoice put the buyer in
    # the ชื่อบริษัทผู้ออกใบกำกับ box and the seller in ชื่อผู้ซื้อ — the two
    # swapped — because the buyer's name happened to be printed first. Such
    # a candidate is held back and used only if the page offers no other.
    deferred = {}
    candidates = []
    for i, line in enumerate(lines[:_SELLER_SEARCH_LINES]):
        if re.search(TAXINV_MARKER, line) or re.search(RECEIPT_MARKER, line):
            continue
        if re.search(r"\d{10,}", line) or _is_field_label_line(line):
            continue
        if len(line) >= 5 and COMPANY_NAME_HINT_RE.search(line):
            if _under_buyer_label(lines, i):
                deferred[i] = line
            else:
                candidates.append(i)
    if candidates:
        i = next((c for c in candidates
                  if THAI_COMPANY_FORM_RE.search(lines[c])), candidates[0])
        # A letterhead reads "<Thai name>" then "<English name>". When the
        # buyer box was OCR'd just above it, the Thai half can fall inside
        # the label's reach and be held back, leaving only the English twin
        # — which named the seller in Latin script on a page that is
        # otherwise entirely Thai. They are the same company, so take the
        # Thai one back.
        twin = deferred.get(i - 1)
        if twin and _is_latin_script(lines[i]) and not _is_latin_script(twin):
            return _trim_unclosed_paren(twin)
        return _trim_unclosed_paren(_merge_split_company_name(lines, i))
    if deferred:
        return _trim_unclosed_paren(_merge_split_company_name(lines, min(deferred)))
    # fallback: first short-ish non-marker line
    for line in lines[:8]:
        if re.search(TAXINV_MARKER, line) or re.search(RECEIPT_MARKER, line):
            continue
        if re.search(r"\d{10,}", line) or _is_field_label_line(line):
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
    # "สำนักงานใหญ่" is a BRANCH marker (head office), not a company name —
    # a letterhead's logo line "ARUN TEST สาขา สำนักงานใหญ่" was picked as
    # the buyer because of it.
    # "สำนักงาน" must START the word: an office-supplies seller's tagline
    # ("จำหน่ายอุปกรณ์ไอที / อุปกรณ์สำนักงาน / และโซลูชั่น...") was read as the
    # buyer because "อุปกรณ์สำนักงาน" contains it.
    # "กรม" ต้องขึ้นต้นคำ ไม่งั้นมันไปตรงกับหน่วยน้ำหนัก "แกรม" ยืนยันจาก
    # ใบจริงของเป๋าเปา: รายการสินค้า "กระดาษAA 80แกรม 1*100(453)" ถูกเลือก
    # เป็นชื่อผู้ซื้อ เพราะดูเหมือนหน่วยงานราชการ ในภาษาไทยไม่มีช่องว่าง
    # คั่นคำ จึงใช้วิธีดูว่าตัวหน้าเป็นอักษรไทยหรือไม่
    r"วิทยาลัย|โรงเรียน|โรงพยาบาล|(?:^|\s)สำนักงาน(?!ใหญ่)|องค์การ|องค์กร|"
    r"(?<![ก-๙])กรม|กระทรวง|เทศบาล|สหกรณ์|"
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
    # "/" and "|" are separators too: a bilingual label is written
    # "นามผู้ซื้อ / Name", and matching the Thai half leaves "/ Name" behind.
    # Stripping the slash reduces it to "Name", which the label blocklist
    # then recognises — without it, "/ Name" was recorded as a buyer.
    val = re.sub(r"^[:：\-–/|｜]+\s*", "", val).strip()
    # A candidate line often carries its own Thai label ("ชื่อลูกค้า :
    # ลูกค้าตัวอย่าง"): the keyword that located it matched the box heading
    # on the line ABOVE, so nothing had consumed this line's label. Drop a
    # leading buyer label up to its separator — the separator is required,
    # so a name that merely starts with one of these words ("ลูกค้าตัวอย่าง")
    # is left intact.
    val = re.sub(
        r"^(?:ชื่อ|นาม|ข้อมูล|รายละเอียด)?(?:ลูกค้า|ผู้ซื้อ|ผู้ชื้อ)\s*[:：/|｜\-–]\s*",
        "", val,
    ).strip()
    # A bilingual label pair prints both halves before the value
    # ("ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด"). The keyword match only
    # consumes the Thai half, leaving "/Customer Name : " glued to the front
    # of the name — drop a leading run of Latin label words up to its colon.
    val = re.sub(r"^[/|\-–]?\s*[A-Za-z][A-Za-z.\s]{0,30}[:：]\s*", "", val).strip()
    # The English half of a bilingual buyer label can sit in front of the
    # name with no punctuation at all: "ชื่อลูกค้า / Customer บริษัท C จำกัด".
    # Matching the Thai half consumed only "ชื่อลูกค้า" and stripping the
    # slash left "Customer" glued to the front of the recorded name.
    shorter = re.sub(
        r"^(?:Customer|Client|Buyer|Purchaser|Name|Company(?:\s*Name)?|"
        r"Bill\s*To|Sold\s*To)\b[\s:：/|｜\-–]*", "", val, flags=re.IGNORECASE
    ).strip()
    if len(shorter) >= 3:
        val = shorter
    # A label OCR mangled past recognition still behaves like one: short,
    # in front of a separator, naming no company. Confirmed live:
    # "นามผู้ซื้อ / Name :" came out "นามสื่อ / Name :", matched none of the
    # patterns above, and the entire line — label included — was recorded
    # as the buyer's name.
    m = re.match(r"^([^:：]{0,40})[:：]\s*(\S.*)$", val)
    if m and not COMPANY_NAME_HINT_RE.search(m.group(1)) and len(m.group(2)) >= 3:
        val = m.group(2).strip()
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
    # An English label half that the blocklist doesn't list verbatim
    # ("Customer Name", "Buyer Company"): Latin text that is itself one of
    # the buyer-label keywords is a label, not a name. A genuinely English
    # buyer ("ABC Co., Ltd.") matches no keyword and still passes.
    if _is_latin_script(val) and any(re.search(k, val, re.IGNORECASE) for k in BUYER_KEYWORDS):
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
    return _is_bare_buyer_label(line)


# Longest line that can still be a buyer-label line rather than prose.
# Generous — a bilingual label with its value on the same line
# ("ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด") is well under it.
_BUYER_LABEL_MAX_LINE_LEN = 100


# A line that is nothing but a generic "name of..." label. These carry no
# buyer keyword at all, so _is_bare_buyer_label never saw them: confirmed
# live, a customer box headed "ลูกค้า / Customer" then labelled its value
# "ชื่อบริษัท", and that label went into the ชื่อผู้ซื้อ box while the name on
# the next line was never reached. Anchored and closed so that a real name
# beginning with the same word ("ชื่อบริษัทในเครือ ...") is not caught.
_BARE_NAME_LABEL_RE = re.compile(
    r"^(?:ชื่อ(?:บริษัท|หน่วยงาน|กิจการ|นิติบุคคล|ร้าน|สถานประกอบการ)?|นาม)"
    r"\s*[:：/|｜\-–]?\s*(?:Company(?:\s*Name)?|Name)?\s*[:：/|｜\-–]?\s*$",
    re.IGNORECASE,
)


def _is_bare_buyer_label(line):
    """True when the line is JUST a buyer label — "ชื่อลูกค้า", "ลูกค้า /
    Customer", "รหัสลูกค้า / CUSTOMER" — rather than a name that happens to
    contain the word. Confirmed live: a buyer really named "ลูกค้าตัวอย่าง"
    was thrown away because it contains "ลูกค้า", and the seller's logo
    line was taken instead.

    Strip the keyword, the English half, and any punctuation; a label has
    almost nothing left ("ชื่อ", "รหัส", ""), a name still has words."""
    if _BARE_NAME_LABEL_RE.match(line.strip()):
        return True
    if not any(re.search(k, line, re.IGNORECASE) for k in BUYER_KEYWORDS):
        return False
    # Strip the plain label words, not BUYER_KEYWORDS — those carry
    # lookbehinds meant for matching, so "ลูกค้า" inside "รหัสลูกค้า" would
    # survive and make a label look like a name.
    rest = re.sub(r"ลูกค้า|ผู้ซื้อ|ผู้ชื้อ|ข้อมูล|รายละเอียด|ชื่อ|นาม|รหัส|เลขที่", "", line)
    rest = re.sub(r"[A-Za-z0-9\s:：/|()\-–.,]+", "", rest)
    return len(rest) <= 6


def _is_latin_script(line):
    """Written in Latin letters rather than Thai. A stray letter inside a
    Thai name ("บริษัท A จำกัด") must not count, so require a few of them
    and no Thai at all."""
    return len(re.findall(r"[A-Za-z]", line)) >= 3 and not re.search(r"[ก-๙]", line)


# How much further away a line above the label may be judged, so that a
# line below it wins only when it is genuinely close.
_ABOVE_LABEL_PENALTY = 2


def _seller_block(lines, seller_name, radius=2):
    """Line numbers of the seller's letterhead — the line carrying its name
    plus its immediate neighbours, which hold the SAME name in the other
    language ("บริษัท ฟาร์มเงินฟาร์มทอง จำกัด" / "FARM NGERN FARM THONG CO.,
    LTD."). Comparing the buyer candidate against the seller's name alone
    misses that translated twin, and a real invoice recorded it as the
    buyer.

    Only a neighbour written in the OTHER script counts — excluding every
    nearby line would swallow the buyer's own name when the two sit next to
    each other, which happens whenever OCR emits the value column first."""
    if not seller_name:
        return frozenset()
    for i, line in enumerate(lines):
        if not _is_seller_name(line.strip(), seller_name):
            continue
        block = {i}
        seller_is_latin = _is_latin_script(line)
        for j in range(max(0, i - radius), min(len(lines), i + radius + 1)):
            neighbour = lines[j].strip()
            if j == i or not neighbour:
                continue
            if (_is_latin_script(neighbour) != seller_is_latin
                    and COMPANY_NAME_HINT_RE.search(neighbour)):
                block.add(j)
        return frozenset(block)
    return frozenset()


def _nearest_entity_name(lines, label_idx, seller_name, max_distance=25, skip_idx=frozenset()):
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
        if j == label_idx or abs(j - label_idx) > max_distance or j in skip_idx:
            continue
        if _skip_as_buyer_candidate(raw):
            continue
        cand = _clean_buyer_value(raw)
        if not _is_plausible_buyer_name(cand) or _is_seller_name(cand, seller_name):
            continue
        if not BUYER_ENTITY_HINT_RE.search(cand):
            continue
        # Nearest wins, with a small preference for lines BELOW the label
        # (normal reading order). Preferring every line below over every
        # line above, regardless of distance, let a tagline thirteen lines
        # down beat the real buyer four lines up.
        dist = j - label_idx
        rank = dist if dist > 0 else -dist + _ABOVE_LABEL_PENALTY
        if best is None or rank < best[0]:
            best = (rank, cand)
    return best[1] if best else None


# Where a company name is printed for a reason other than being a party
# to the sale: the seller's own bank details at the foot of the page, the
# "ในนาม / For <company>" above the signature.
_BANK_CONTEXT_RE = re.compile(
    r"ชื่อบัญชี|เลขที่บัญชี|ธนาคาร|ในนาม|โอนเงิน|Bank|Account",
    re.IGNORECASE,
)


def _buyer_by_position(lines, seller_name, seller_block):
    """The buyer when the document labels nobody.

    Plenty of invoices print the two parties as two address blocks and
    label neither — the letterhead, then the customer below it. Losing the
    buyer there is expensive: with no name the document is classified ย่อ,
    and ม.86/6 then wipes the subtotal and VAT it plainly showed. So take
    the first OTHER company named after the seller's own block, which is
    where the customer block sits. Only a line that names a company counts
    — this is a positional guess, and a guess needs strong evidence."""
    if not seller_name:
        return None
    start = max(seller_block) + 1 if seller_block else 0
    for j in range(start, len(lines)):
        line = lines[j].strip()
        if not line or j in seller_block:
            continue
        if DOC_FURNITURE_RE.search(line) or TABLE_HEADER_LINE_RE.search(line):
            continue
        if SIGNATURE_CONTEXT_RE.search(line) or _BANK_CONTEXT_RE.search(line):
            continue
        if not COMPANY_NAME_HINT_RE.search(line):
            continue
        cand = _clean_buyer_value(line)
        if _is_plausible_buyer_name(cand) and not _is_seller_name(cand, seller_name):
            return cand
    return None


def extract_buyer_name(text, seller_name=None):
    lines = normalize_thai_text(text or "").splitlines()
    seller_block = _seller_block(lines, seller_name)
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
            # A field label is a short line. The words "ผู้ซื้อ" and "ลูกค้า"
            # also appear in the conditions printed at the foot of an
            # invoice ("...ยังคงเป็นทรัพย์สินของผู้ขายจนกว่าผู้ซื้อได้ชำระ
            # เงิน..."), and a name must never be read out of that.
            if len(line.strip()) > _BUYER_LABEL_MAX_LINE_LEN:
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
                if i + j in seller_block:
                    continue
                nxt = lines[i + j]
                # หยุดที่หัวตารางรายการสินค้า ไม่ใช่ข้ามมันไป
                #
                # ชื่อผู้ซื้อไม่เคยอยู่ใต้หัวตาราง ของที่อยู่ใต้นั้นคือชื่อ
                # สินค้า ซึ่งเป็นข้อความไทยยาว ๆ ที่หน้าตาผ่านทุกด่าน
                # ยืนยันจากใบเป๋าเปา: การสแกนเดินลงไปเก้าบรรทัดจนถึงกลาง
                # ตารางสินค้าแล้วคืนชื่อสินค้ามาเป็นชื่อผู้ซื้อ
                #
                # ที่หยุดได้โดยไม่เสียอะไร เพราะถ้าค่าจริงอยู่ใต้หัวตาราง
                # จริง ๆ (OCR สลับบล็อก) _nearest_entity_name ด้านล่างยัง
                # ค้นทั้งหน้าอยู่ดี
                if TABLE_HEADER_LINE_RE.search(nxt) or _is_table_column_header(lines, i + j):
                    break
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
            near = _nearest_entity_name(lines, i, seller_name, skip_idx=seller_block)
            if near:
                return near
            if fallback:
                return fallback
    # No buyer label anywhere on the page — see _buyer_by_position.
    return _buyer_by_position(lines, seller_name, seller_block)


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


def _vat_rate_ok(subtotal, vat, exempt=0.0):
    """VAT เป็น 7% ของฐานภาษี (= ยอดก่อนภาษี − ส่วนที่ยกเว้น)

    exempt=0 คือใบปกติที่ทั้งใบเสีย 7% เท่ากันหมด ซึ่งเป็นค่าเริ่มต้น
    ผู้เรียกที่พิสูจน์ได้ว่าใบนี้เป็นอัตราผสมเท่านั้นจึงจะส่ง exempt มา
    — ดู _exempt_portion ว่า "พิสูจน์" แปลว่าอะไร"""
    if subtotal is None or vat is None:
        return False
    base = subtotal - (exempt or 0.0)
    if base <= 0:
        return vat == 0
    return abs(vat / base - VAT_RATE) <= _RATE_TOL


# ตัวเลขทุกตัวที่ "พิมพ์อยู่จริง" บนหน้านั้น ใช้เป็นหลักฐานใน _exempt_portion
_ANY_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _page_numbers(text):
    """เซ็ตของตัวเลขบวกทุกตัวที่ปรากฏบนหน้า

    ไม่กรองอะไรเลยโดยตั้งใจ — หน้าที่ของมันคือตอบว่า "เลขนี้มีอยู่บนกระดาษ
    ไหม" ให้ตรงตามความจริง ส่วนการตัดสินว่าเลขไหนมีความหมายเป็นเรื่องของ
    ผู้เรียก"""
    out = set()
    for token in _ANY_NUMBER_RE.findall(text or ""):
        val = _clean_number(token)
        if val is not None and val > 0:
            out.add(round(val, 2))
    return out


def _exempt_portion(subtotal, vat, numbers):
    """ถ้าใบนี้เป็น VAT อัตราผสม คืนค่าส่วนของยอดก่อนภาษีที่ไม่ถูกคิด VAT

    ทำไมต้องมี: ใบกำกับที่ขายทั้งของที่เสีย VAT 7% และของที่ยกเว้น VAT
    (ผลไม้สด นม ค่าขนส่ง) พิมพ์ยอดก่อนภาษีเป็นผลรวมของทั้งสองส่วน แต่พิมพ์
    VAT เป็น 7% ของเฉพาะส่วนที่เสียภาษี ความสัมพันธ์ "VAT = 7% ของยอดก่อน
    ภาษี" จึงไม่จริงบนใบพวกนี้ ทั้งที่อ่านถูกทุกตัว. ยืนยันจากใบจริง
    (Makro หน้า 9 ของกองใบจริง): แถว 0.00% 81.00 บวกแถว 7.00%
    195.33/13.67/209.00 ได้ TOTAL 276.33/13.67/290.00 — 276.33 + 13.67
    เท่ากับ 290.00 พอดี แต่ 13.67 เป็นแค่ 4.95% ของ 276.33 ระบบเดิมจึง
    ตีว่าอ่านผิดและขึ้นเตือนทุกครั้ง ทั้งที่ไม่มีอะไรผิด

    คืน 0.0 เมื่อเป็นใบ 7% ธรรมดา, คืน None เมื่อ VAT เข้ากับยอดก่อนภาษี
    ไม่ได้ไม่ว่าจะตีความแบบไหน (= อ่านผิดจริง ต้องเตือน)

    การจะยอมรับว่าเป็นอัตราผสมต้องครบทั้งสามข้อ ไม่ใช่แค่ "หารแล้วลงตัว":
      1. VAT เป็น 7% ของฐานภาษี b พอดี
      2. ส่วนที่เหลือ (subtotal − b) มากกว่าศูนย์
      3. ทั้ง b และส่วนที่เหลือ ต้องเป็นตัวเลขที่พิมพ์อยู่บนใบจริง
    ข้อ 3 คือตัวกันเดา: ถ้าไม่มีข้อนี้ ยอดคู่ไหนก็ "เป็นอัตราผสมได้" เสมอ
    เพราะประดิษฐ์ b = vat/0.07 ขึ้นมาเองได้เรื่อย ๆ การบังคับให้ทั้งฐานภาษี
    และส่วนยกเว้นปรากฏบนกระดาษ ทำให้เงื่อนไขแน่นพอ ๆ กับสมการสองชั้นที่ใช้
    ตรวจใบปกติ"""
    if subtotal is None or vat is None:
        return None
    if _vat_rate_ok(subtotal, vat):
        return 0.0
    if not numbers or vat <= 0 or subtotal <= 0:
        return None
    for base in numbers:
        if base >= subtotal or not _vat_rate_ok(base, vat):
            continue
        rest = round(subtotal - base, 2)
        if rest > 0 and rest in numbers:
            return rest
    return None


def _fmt_baht(n):
    """2,571.03 / 140 — show satang only when there are any."""
    if n is None:
        return "—"
    s = f"{round(n, 2):,.2f}"
    return s[:-3] if s.endswith(".00") else s


def totals_mismatch_reason(subtotal, vat, total, exempt=0.0):
    """The warning shown when the three amounts contradict each other, with
    the actual figures in it so the user can see what to fix without
    reopening the document. Returns None when they agree (or when there
    isn't enough to check), so a correctly-read invoice stays clean — a
    figure that reconcile_totals derived and verified is not a problem and
    must not raise a warning of its own.

    exempt เป็นส่วนของยอดก่อนภาษีที่ได้รับยกเว้น VAT ซึ่งพิสูจน์มาแล้วจาก
    ตัวเลขบนหน้านั้น (ดู _exempt_portion). ใบอัตราผสมที่อ่านถูกจะต้องไม่
    ขึ้นเตือน เพราะการเตือนใบที่ถูกอยู่แล้วทำให้คนเลิกเชื่อคำเตือนทั้งระบบ"""
    if subtotal is not None and vat is not None and not _vat_rate_ok(subtotal, vat, exempt):
        base = subtotal - (exempt or 0.0)
        expected = round(base * VAT_RATE, 2)
        return (f"⚠️ ยอดไม่สอดคล้องกัน: VAT ที่ระบุ ({_fmt_baht(vat)} บาท) ไม่ตรงกับ 7% "
                f"ของยอดก่อนภาษี (ควรเป็น {_fmt_baht(expected)} บาท) — โปรดตรวจสอบ")
    if None not in (subtotal, vat, total) and not _amounts_balance(subtotal, vat, total):
        return (f"⚠️ ยอดไม่สอดคล้องกัน: ยอดก่อนภาษี + VAT ({_fmt_baht(subtotal + vat)} บาท) "
                f"ไม่เท่ากับยอดรวม ({_fmt_baht(total)} บาท) — โปรดตรวจสอบ")
    return None


def reconcile_totals(subtotal, vat, total, numbers=None):
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
    into the warning the user sees.

    numbers คือตัวเลขทุกตัวบนหน้านั้น ส่งมาเพื่อให้รู้จักใบ VAT อัตราผสม
    ซึ่งยอดบวกกันลงตัวแต่ VAT ไม่ใช่ 7% ของยอดก่อนภาษี — ใบพวกนี้อ่านถูก
    แล้วและต้องคืนค่าเดิมทันที ห้ามสลับตำแหน่งหรือคำนวณทับ"""
    if _amounts_balance(subtotal, vat, total) and (
        _vat_rate_ok(subtotal, vat)
        or _exempt_portion(subtotal, vat, numbers) is not None
    ):
        return subtotal, vat, total

    # Before computing anything, consider that all three figures were read
    # correctly but landed on the wrong fields — a column of labels paired
    # with its column of values one position out puts the total in the VAT
    # box, which is what the app showed on a real invoice (VAT 511.00,
    # total 33.43, for 477.57 + 33.43 = 511.00).
    #
    # Only one arrangement of three amounts can satisfy both relations at
    # once: v = 0.07s forces v < s, and s + v = t forces t largest, so the
    # smallest figure is the VAT, the largest the total. That makes the
    # reordering safe — a wrong permutation cannot pass both checks — and
    # it is tried before deriving anything, since rearranging what the
    # document actually prints beats replacing it with arithmetic.
    printed = (subtotal, vat, total)
    if all(x is not None for x in printed):
        for s, v, t in itertools.permutations(printed):
            if _amounts_balance(s, v, t) and _vat_rate_ok(s, v):
                return s, v, t

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
    # Presence, not exact length. A taxpayer ID that came out a digit short
    # is an OCR defect to flag (see build_review_reasons), not grounds for
    # reclassifying a full tax invoice as ใบย่อ and discarding its VAT.
    has_tax_id = bool(fields.get("seller_tax_id"))
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
    elif not has_valid_tax_id_format(fields["seller_tax_id"]):
        digits = re.sub(r"\D", "", fields["seller_tax_id"])
        reasons.append(
            f"เลขประจำตัวผู้เสียภาษีผู้ขายมี {len(digits)} หลัก (ต้องเป็น 13 หลัก) — โปรดตรวจสอบ"
        )
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
            fields.get("subtotal"), fields.get("vat"), fields.get("total"),
            fields.get("_vat_exempt") or 0.0,
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
# "exempt" and "deduct" are here purely to keep the label run aligned with
# the value run. A totals box lists every line it has — VAT-exempt goods,
# a deposit deduction — and the pairing is positional, so a label this
# didn't recognize used to drop out of the list and shift every figure
# after it onto the wrong field. Their values are matched and discarded.
_TOTALS_BLOCK_KEYS = [
    ("exempt", [r"ยกเว้นภาษีมูลค่าเพิ่ม", r"ยกเว้น\s*VAT", r"Non[-\s]?VAT", r"VAT\s*Exempt"]),
    ("subtotal", [kw for kw in SUBTOTAL_KEYWORDS if kw != r"จำนวนเงิน"]),
    ("discount", [r"ส่วนลด", r"Discount"]),
    ("deduct", [r"หัก\s*เงิน", r"เงินมัดจำ", r"หักมัดจำ", r"Deposit", r"Deduct"]),
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
PURE_NUMBER_LINE_RE = re.compile(
    r"^[-+]?\d[\d,]*(?:\.\d+)?\s*(?:[.,]-)?\s*%?\s*(?:บาท|บ\.|Baht|THB|฿)?\s*$",
    re.IGNORECASE,
)


# A bare English totals word carries no information of its own — it is the
# translation of the Thai label above it. Needed because such a pair can
# classify to DIFFERENT keys: "รวมเงิน" reads as the subtotal while its twin
# "Total" reads as the grand total, which split one field into two labels
# and threw the whole box out of alignment with its values.
GENERIC_TOTALS_WORD_RE = re.compile(
    r"^(?:Grand\s*)?(?:Sub\s*)?(?:Total|Amount|Discount|Deposit|VAT(?:\s*7\s*%?)?|"
    r"Net\s*Total|Balance)\s*$",
    re.IGNORECASE,
)


def _is_translation_pair(a, b):
    """True when two label lines look like the Thai and English halves of
    ONE field ("ภาษีมูลค่าเพิ่ม 7%" / "VAT 7%") rather than two separate
    fields — exactly one of them is written in Latin script.

    This decides whether consecutive labels that classify the same way get
    collapsed into one. Collapsing unconditionally was wrong: a real
    invoice ends with "จำนวนเงินรวมทั้งสิ้น" and then a summary row
    "จำนวนรวมทั้งสิ้น", two Thai lines with two separate figures, and
    merging them shifted every amount in the box onto the wrong field."""
    a_latin = bool(re.search(r"[A-Za-z]", a))
    b_latin = bool(re.search(r"[A-Za-z]", b))
    return a_latin != b_latin


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
    numbers = _page_numbers(text)
    n = len(lines)
    for start in range(n):
        labels = []
        last_label = ""
        last_label_idx = -2
        j = start
        unclassified_streak = 0
        while (j < n and lines[j] and not PURE_NUMBER_LINE_RE.match(lines[j])
               and not TABLE_HEADER_LINE_RE.search(lines[j])):
            key = _classify_totals_label(lines[j])
            if key is not None:
                twin = labels and last_label_idx == j - 1 and _is_translation_pair(
                    last_label, lines[j]
                ) and (labels[-1] == key or GENERIC_TOTALS_WORD_RE.match(lines[j].strip()))
                if twin:
                    pass  # the English half of the label above — one field
                else:
                    labels.append(key)
                last_label, last_label_idx = lines[j], j
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
            return _pair_totals(labels, values)
        # More figures than labels means a label went missing — typically
        # the first, when OCR drops the signature block into the middle of
        # the label run and breaks it in two (confirmed live: five labels
        # against six figures). Try aligning from the end, then from the
        # start, and accept only a pairing the arithmetic agrees with.
        if len(values) > len(labels):
            for offset in (len(values) - len(labels), 0):
                candidate = _pair_totals(labels, values[offset:offset + len(labels)])
                if _totals_pairing_is_sound(candidate, numbers):
                    return candidate
        # And the mirror: more labels than figures, because the box's last
        # row was emitted somewhere else. Confirmed live: a totals box of
        # four labels ("สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม", "สินค้าที่เสียภาษี
        # มูลค่าเพิ่ม", "ภาษีมูลค่าเพิ่ม VAT 7%", "หัก เงินมัดจำ") against
        # three figures was skipped entirely, and the next start — one
        # label short — paired those same figures one row out, recording
        # the exempt 0.00 as the subtotal and the subtotal as the VAT.
        # Front-aligned first, since it is the trailing value that is
        # missing; end-aligned after, and only a sound pairing is taken.
        if len(labels) > len(values):
            for candidate_labels in (labels[:len(values)], labels[-len(values):]):
                candidate = _pair_totals(candidate_labels, values)
                if _totals_pairing_is_sound(candidate, numbers):
                    return candidate
    return {}


_ARITH_SCAN_MIN_RUN = 3


def _totals_from_number_run(text):
    """Find the three amounts by arithmetic alone, ignoring every label.

    Last resort for a totals box OCR interleaved beyond repair. Confirmed
    live: an invoice emitted five of its six totals labels, then wandered
    back into the last row of the items table ("V", "5", "กล่อง", "90.00",
    "0.00", "450.00"), then the sixth label, then all six figures — so no
    label run ever met its own values and every field fell through to a
    keyword search that picked up an item number and a postcode.

    The figures survive that intact, though: they are still a column of
    consecutive numbers, and within it exactly one triple satisfies BOTH
    of the invoice's arithmetic invariants at once — VAT is 7% of the
    subtotal, and the two add up to the total. Two simultaneous equations
    over a handful of numbers is a far stronger claim than any position,
    which is why this is allowed to override a reading nothing else
    agreed with. Where a page offers several, the largest total wins — a
    per-section subtotal can also balance, the grand total is the bigger.
    """
    lines = [l.strip() for l in text.splitlines()]
    numbers = _page_numbers(text)
    best = None
    run = []
    for line in lines + [""]:
        if line and PURE_NUMBER_LINE_RE.match(line):
            val = _clean_number(line)
            if val is not None:
                run.append(val)
                continue
        if len(run) >= _ARITH_SCAN_MIN_RUN:
            found = _balanced_triple(run, numbers)
            if found and (best is None or found[2] > best[2]):
                best = found
        run = []
    if best is not None:
        return best

    # ไม่มีแถวไหนเก็บครบทั้งสามตัว — ขยายไปทั้งหน้า
    #
    # ยืนยันจากใบจริง B2S: ค่าทั้งสี่ของกล่องยอดถูกตัดขาดจากป้ายด้วยแถว
    # ":" สี่บรรทัด แล้วถูกสลับฟันปลากับคอลัมน์วิธีชำระเงิน กลายเป็น
    #     0.00 / 52.00 / ชำระโดย / 0.00 / QRPP... / 52.00 / 52.00 /
    #     Change / 0.00 / 48.60 / 3.40
    # ไม่มีชุดสามตัวติดกันชุดไหนที่ใช้ได้เลย ทั้งที่ 48.60 + 3.40 = 52.00
    # อยู่บนหน้านั้นครบทุกตัว แค่ไม่ได้อยู่ติดกัน
    #
    # ที่ทำแบบนี้ได้โดยไม่ใช่การเดา เพราะเงื่อนไขยังเป็นสมการสองชั้นเหมือน
    # เดิม และยังบังคับว่าต้องมีคำตอบเดียว หน้านี้มีตัวเลข 20 ตัว (รวม
    # รหัสไปรษณีย์ ปี พ.ศ. เลขบาร์โค้ดที่ตัดทิ้งไปแล้ว) และมีชุดเดียว
    # เท่านั้นที่ผ่านทั้งสองสมการ ยิ่งตัวเลขบนหน้าเยอะ โอกาสเจอชุดที่สอง
    # ยิ่งมาก ซึ่งจะทำให้คืน None แล้วไปจบที่ "ให้คนตรวจ" — ผิดพลาดไป
    # ในทางที่ปลอดภัย ไม่ใช่ทางที่กรอกเลขมั่ว
    #
    # วางไว้หลังสุดเพราะตัวเลขที่อยู่ติดกันเป็นหลักฐานที่ดีกว่า: มันบอกว่า
    # ทั้งสามตัวมาจากกล่องเดียวกันบนกระดาษ
    found = _balanced_triple(sorted(numbers), numbers)
    if found is not None:
        return found

    # ชั้นสุดท้าย: เผื่อว่าจุดทศนิยมหายไป
    #
    # ใบเล่มกระดาษเขียนบาทกับสตางค์คนละช่องในตาราง ไม่มีจุดคั่น OCR จึง
    # คายออกมาติดกันเป็นจำนวนเต็ม ยืนยันจากใบ หจก.ภควดีปิโตรเลียม:
    # 859.81 / 60.19 / 920.00 ออกมาเป็น "85981" / "6019" / "920"
    #
    # การหารร้อยเป็นการเดา — แต่เป็นการเดาที่ตรวจสอบตัวเองได้ เพราะยังต้อง
    # ผ่านสมการสองชั้นและต้องมีคำตอบเดียวเหมือนเดิม
    #
    # ที่ต้องแยกเป็นชั้นต่างหาก ไม่ใช่โยนรวมไปกับชั้นบน เพราะตัวเลือกที่
    # เพิ่มขึ้นเท่าตัวทำให้เกิดคำตอบซ้อนได้ง่ายขึ้นมาก วัดกับใบจริงของ
    # เป๋าเปา: เติมจุดแล้วได้สามคำตอบ โดยตัวปลอมตัวหนึ่งคือ 22.33 ซึ่งมา
    # จากเลขที่ใบกำกับ "POSS6807/2233" ถ้ารวมสองชั้นเข้าด้วยกัน ใบที่ชั้น
    # บนเคยตอบถูกอยู่แล้วจะกลายเป็นกำกวมและตอบไม่ได้ — ได้อย่างเสียอย่าง
    # แยกชั้นแล้วมีแต่ได้ เพราะชั้นนี้ทำงานเฉพาะตอนที่ชั้นบนไม่เจออะไรเลย
    padded = set(numbers)
    for token in _ANY_NUMBER_RE.findall(text or ""):
        if "." in token:
            continue
        val = _clean_number(token)
        if val is not None and val >= 100:
            padded.add(round(val / 100.0, 2))
    if len(padded) == len(numbers):
        return None
    return _balanced_triple(sorted(padded), padded)


def _balanced_triple(values, numbers=None):
    """The one (subtotal, vat, total) among `values` that satisfies both
    invariants, or None. Returns None when several do and they cannot be
    explained as one invoice — an ambiguous run is no better evidence than
    no run at all."""
    seen = []
    for v in values:
        if v > 0 and not any(abs(v - o) < 0.005 for o in seen):
            seen.append(v)
    hits = []
    for subtotal in seen:
        for vat in seen:
            if _exempt_portion(subtotal, vat, numbers) is None:
                continue
            for total in seen:
                if _amounts_balance(subtotal, vat, total):
                    hits.append((subtotal, vat, total))
    if len(hits) == 1:
        return hits[0]
    # ใบ VAT อัตราผสมให้มากกว่าหนึ่งคำตอบเสมอ และนั่นไม่ใช่ความกำกวม:
    # แถวสรุปของกลุ่ม 7% บวกกันลงตัวในตัวมันเอง (195.33 + 13.67 = 209.00)
    # และแถว TOTAL ของทั้งใบก็บวกกันลงตัวเช่นกัน (276.33 + 13.67 = 290.00)
    # สองแถวนี้แยกจากกันได้ด้วยข้อเท็จจริงเดียว — VAT ของทั้งใบคือ VAT ของ
    # กลุ่มที่เสียภาษี จึงเป็น "ตัวเดียวกัน" ส่วนยอดรวมของทั้งใบย่อมใหญ่กว่า
    # ถ้าคำตอบที่ได้มา VAT ไม่ตรงกัน แปลว่าเป็นตัวเลขจากคนละใบ/คนละตาราง
    # อันนั้นกำกวมจริงและต้องคืน None ตามเดิม
    if hits and all(abs(h[1] - hits[0][1]) < 0.005 for h in hits):
        return max(hits, key=lambda h: h[2])
    return None


def _pair_totals(labels, values):
    result = {}
    for key, val in zip(labels, values):
        result[key] = val  # a later same-key label (e.g. the post-discount
        # subtotal) intentionally overwrites an earlier one, matching
        # _find_after_keyword's own priority
    return result


def _totals_pairing_is_sound(pairing, numbers=None):
    """Only trust a guessed alignment if the three amounts it produces add
    up and carry a correct 7% rate — a wrong offset cannot fake both.

    บนใบอัตราผสม "7% ของยอดก่อนภาษี" ใช้ไม่ได้ ที่ใช้แทนคือส่วนยกเว้นที่
    พิสูจน์ได้จากตัวเลขบนหน้า ซึ่งยังเป็นเงื่อนไขสองชั้นเหมือนเดิม"""
    subtotal = _clean_number(pairing.get("subtotal"))
    vat = _clean_number(pairing.get("vat"))
    total = _clean_number(pairing.get("total"))
    if _amounts_balance(subtotal, vat, total) and (
        _vat_rate_ok(subtotal, vat)
        or _exempt_portion(subtotal, vat, numbers) is not None
    ):
        return True
    # A box that prints its grand total apart from the rest yields a
    # pairing with no total in it at all, which the balance test can never
    # accept. A VAT that is exactly 7% of the subtotal printed beside it
    # is evidence enough on its own: shift the alignment by one row and an
    # unrelated figure lands there and the rate falls apart. The subtotal
    # must be non-zero, or an exempt-goods 0.00 paired with a 0.00 would
    # satisfy any rate at all.
    if total is None and subtotal is not None and vat is not None:
        return subtotal > 0 and _vat_rate_ok(subtotal, vat)
    return False


# Some invoices' document-info box (เลขที่เอกสาร/วันที่เอกสาร/เลขที่เอกสารอ้างอิง/
# วันที่เอกสารอ้างอิง/เลขที่ใบสั่งซื้อ) gets OCR'd the same column-major way as
# the totals box: ALL the label lines (Thai+English pairs) first, then ALL
# the value lines after — and confirmed on a real invoice, this run can be
# up to 10 label lines before the first value, far past a small lookahead.
# Unlike the totals box, a trailing field is often blank (no printed value
# at all, e.g. an empty Purchase Order No.), so the value run can be
# SHORTER than the label run — pair up to the shorter length instead of
# requiring an exact match.
# A bilingual document box labels the same fields as "เลขที่ / NO.",
# "วันที่ / DATE", "เครดิต / CREDIT", ... — the doc_no/doc_date patterns for
# those are anchored to the whole line so they can't swallow
# "เลขที่ใบสั่งซื้อ / PO.NO", which is a different field checked further
# down. credit/due_date/salesman/customer_code carry no data we keep; they
# exist so every label in the box classifies and the positional pairing
# with the value run stays aligned.
_DOC_INFO_BLOCK_KEYS = [
    # The English half may name the document in the middle — "เลขที่ /
    # Invoice No.", "วันที่ / Invoice Date" — which the bare "เลขที่ / No."
    # form did not match, so the box's first label was invisible.
    ("doc_no", [r"เลขที่เอกสาร(?!อ้างอิง)", r"Document\s*No",
                r"^เลขที่?\s*[/／]\s*(?:Tax\s*)?(?:Invoice|Doc(?:ument)?)?\s*No\.?\s*$",
                r"^เลขที่ใบเสร็จ\s*$", r"^Rece[ij]pt\s*N[og0]\.?\s*$"]),
    ("doc_date", [r"วันที่เอกสาร(?!อ้างอิง)", r"Document\s*Date",
                  r"^วันที่?\s*[/／]\s*(?:Tax\s*)?(?:Invoice|Doc(?:ument)?)?\s*Date\.?\s*$",
                  r"^วันที่\s*$", r"^Date\s*$"]),
    ("doc_ref_no", [r"เลขที่เอกสารอ้างอิง", r"Document\s*Ref"]),
    ("doc_ref_date", [r"วันที่เอกสารอ้างอิง", r"Date\s*of\s*Ref"]),
    # A POS receipt heads its box with "แผ่นที่ / เลขที่ใบเสร็จ /
    # พนักงานเก็บเงิน / วันที่" and OCR reads the column down, so these
    # exist to keep the label run aligned with the value run the same way
    # credit/salesman do. "N[og0]" because OCR read "Receipt No" as
    # "Recejpt Ng".
    ("page", [r"^แผ่นที่\s*$", r"^Sheet\s*$"]),
    ("cashier", [r"^Cashier\s*$", r"^พนักงานเก็บเงิน\s*$"]),
    ("credit", [r"^เครดิต\s*[/／]?", r"^Credit\b"]),
    ("due_date", [r"วันครบกำ?า?หนด", r"Due\s*Date"]),
    ("po_no", [r"เลขที่ใบสั่งซื้อ", r"Purchase\s*Order\s*No", r"PO\.?\s*No"]),
    ("salesman", [r"พนักงานขาย", r"Sale?s?man"]),
    ("customer_code", [r"รหัสลูกค้า", r"Customer\s*(?:Code|No)", r"^.{0,20}[/／]\s*CUSTOMER\s*$"]),
]

# A "value" line here is a single alphanumeric token with no spaces (a doc
# number, a reference number, or a dd/mm/yyyy date) — deliberately narrower
# than PURE_NUMBER_LINE_RE since these values aren't always pure digits.
# A date spelled out in Thai is a value too, but it has spaces in it; both
# shapes are covered by _is_doc_value_line, which is what the block
# extractor uses. Confirmed live: a box whose values ran "01210" / "1
# กุมภาพันธ์ 2568" / "1 มีนาคม 2568" was cut off after the first one, so the
# invoice was filed with no date at all.
DOC_VALUE_LINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/.]*$")


# A document box's value column holds tokens ("INV-2568-004", "01210") and
# dates, and a Thai date is spelled out ("1 มีนาคม 2568") — a shape the
# token pattern cannot match, which left such a value column looking one
# line long.
_THAI_DATE_LINE_RE = re.compile(
    r"^\d{1,2}\s*(?:" + "|".join(re.escape(m) for m in THAI_MONTHS) + r")\s*\d{2,4}$"
)


def _is_doc_value_line(line):
    return bool(DOC_VALUE_LINE_RE.match(line) or _THAI_DATE_LINE_RE.match(line))


# How far above its values a document box's labels may be looked for.
_DOC_INFO_LABEL_REACH = 40


def _doc_info_by_order(lines):
    """Pair a document box's labels with its values by ORDER alone.

    _extract_doc_info_block needs the labels to form a run. Confirmed live:
    an invoice's label column came out with the CUSTOMER box and the whole
    items table threaded through it —

        เลขที่/ Invoice No ... ที่อยู่ / Address ... 456/89 ถนนสุขุมวิท ...
        วันที่ / Date ... อีเมล / Email ... ล่าดับ ... HDD External 2TB ...
        ครบกำหนด / Due Date / 01210 / 1 มีนาคม 2568 / 1 เมษายน 2568

    — so no two labels were ever adjacent and the box yielded nothing,
    while the forward search for the number walked into the address and
    returned "456/89".

    The labels keep their order even when scattered, so here they are read
    in order and zipped onto the value run. The counts must match exactly
    and the result must still pass _doc_info_pairing_is_sound, which is
    what stops an items-table fragment being paired with them."""
    n = len(lines)
    i = 0
    while i < n:
        if not (lines[i] and _is_doc_value_line(lines[i])):
            i += 1
            continue
        start = i
        values = []
        while i < n and lines[i] and _is_doc_value_line(lines[i]):
            values.append(lines[i])
            i += 1
        if len(values) < 2:
            continue
        labels = []
        last_label = -1
        for j in range(max(0, start - _DOC_INFO_LABEL_REACH), start):
            key = _classify_doc_info_label(lines[j])
            if key is not None and (not labels or labels[-1] != key):
                labels.append(key)
            if key is not None:
                last_label = j
        if len(labels) != len(values):
            continue
        # A heading BETWEEN two of the labels is fine — that is exactly the
        # split box this function exists for. A heading between the last
        # label and the values is not: it means the run belongs to the
        # items table, not to the box. Confirmed live: "6" / "10" / "130.-"
        # from an item row paired with three document-box labels.
        if any(TABLE_HEADER_LINE_RE.search(lines[j]) or _is_table_column_header(lines, j)
               for j in range(last_label + 1, start) if lines[j]):
            continue
        pairing = dict(zip(labels, values))
        if _doc_info_pairing_is_sound(pairing):
            return pairing
    return {}


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
        while j < n and lines[j] and not _is_doc_value_line(lines[j]):
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
        # The values don't always start where the labels end. Confirmed
        # live: OCR dropped the buyer's address and taxpayer ID into the
        # middle of the document box, breaking the label run and putting a
        # stray 13-digit number where the values should start. So scan
        # forward for runs of value-shaped lines and take the first run
        # that yields a sound pairing — a document number is not a taxpayer
        # ID, and a document date has to be a real date.
        k = j
        while k < n and k - j <= _DOC_INFO_MAX_GAP:
            # The document box sits above the items table, so its values
            # are never found past that table's heading. Confirmed live: a
            # box whose own values failed to pair kept scanning, reached
            # the first item row ("6", "10", "130.-") and paired against
            # it, and the invoice was filed under the number "130.-".
            if lines[k] and (TABLE_HEADER_LINE_RE.search(lines[k])
                             or _is_table_column_header(lines, k)):
                break
            if not (lines[k] and _is_doc_value_line(lines[k])):
                k += 1
                continue
            values = []
            while k < n and lines[k] and _is_doc_value_line(lines[k]):
                values.append(lines[k])
                k += 1
            pairing = dict(zip(labels, values))  # zip stops at the shorter
            # list, so a blank trailing field just isn't included
            if _doc_info_pairing_is_sound(pairing):
                return pairing
    return _doc_info_by_order(lines)


# How far past the labels a document box's values may sit before we stop
# believing they belong together.
_DOC_INFO_MAX_GAP = 15


def _doc_info_pairing_is_sound(pairing):
    """Reject a label/value alignment that produced something a document
    number and date plainly are not."""
    doc_no = pairing.get("doc_no")
    if not doc_no or re.fullmatch(r"\d{13}", doc_no):
        # Exactly 13 digits is a taxpayer ID, not a document number. The
        # bound used to be 10-or-more, which also threw away a POS
        # receipt's own 12-digit number.
        return False
    if _parse_thai_date(doc_no):
        return False  # a date landed in the number's slot: misaligned by one
    if not re.search(r"\d", doc_no):
        # Every document number carries a digit. A bare word means the
        # scan ran past the values — which are printed ": INV-6809-042",
        # behind a colon — and reached the items table's heading, which is
        # how an invoice came to be filed under the number "ITEM".
        return False
    doc_date = pairing.get("doc_date")
    if doc_date is not None and _parse_thai_date(doc_date) is None:
        return False
    return True


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

    # The document box pairs its date with its number by position, which
    # beats hunting for a "วันที่" keyword — on a column-major read the real
    # date label is nowhere near its value, and the scan can wander into
    # the terms printed at the foot of the page. Confirmed live: an invoice
    # dated 31/12/2568 was filed as 2026-01-03, taken from "...คำสั่งซื้อ
    # ดำเนินการต่ออีกครั้งวันที่ 3 มกราคม 2569" in the holiday notice. Only
    # used when it parses, so a mispaired block can't override a good date.
    block_date = doc_info_block.get("doc_date")
    if block_date:
        block_iso = _parse_thai_date(block_date)
        if block_iso:
            date_raw, date_iso = block_date, block_iso

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
    page_numbers = _page_numbers(text)
    subtotal, vat, total = reconcile_totals(subtotal, vat, total, page_numbers)

    # The three figures don't hang together, so this reading is wrong
    # somewhere — whether it came from a label pairing or a keyword search
    # makes no difference, a wrong answer is a wrong answer. Let the
    # arithmetic scan speak: see _totals_from_number_run.
    #
    # Pairing with a label used to be treated as proof enough to block the
    # scan. It isn't. Confirmed live on a Makro receipt: its totals row is
    # labelled "ราคาสินค้า / ภาษี / รวม" — three words too generic to be
    # keywords — so the block matched the ITEMS table's "มูลค่าสินค้า"
    # heading instead and paired it with the first item row, filing a
    # 356.00 receipt as 96.00 + 1.00 VAT. The scan had the right answer
    # (332.71 + 23.29 = 356.00, and 23.29 is exactly 7%) and was ignored.
    #
    # What keeps this safe is the scan itself, not the guard: it demands a
    # run of figures holding exactly ONE triple that satisfies both
    # invariants at once. An invoice whose printed amounts genuinely
    # disagree offers no such triple, so it stays flagged rather than
    # being quietly rewritten.
    if not (
        subtotal and vat and total
        and _amounts_balance(subtotal, vat, total)
        and (
            _vat_rate_ok(subtotal, vat)
            or _exempt_portion(subtotal, vat, page_numbers) is not None
        )
    ):
        scanned = _totals_from_number_run(text)
        if scanned:
            subtotal, vat, total = scanned

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
        # ส่วนของยอดก่อนภาษีที่ได้รับยกเว้น VAT — 0.0 คือใบ 7% ธรรมดา
        # None คือยอดที่อธิบายไม่ได้ ซึ่ง build_review_reasons จะเตือน
        "_vat_exempt": _exempt_portion(subtotal, vat, page_numbers),
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
