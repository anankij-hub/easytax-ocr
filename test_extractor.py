"""Unit tests for extractor.py that don't require a real OCR/Tesseract run.

These feed in text that approximates what Tesseract would output for a
Thai tax invoice, so we can validate the regex/field-extraction logic on
its own. Run: python3 test_extractor.py
"""
import sys

import extractor

# The Windows console defaults to cp874 here, which has Thai but no emoji —
# printing the ⚠️ in a warning message would raise UnicodeEncodeError and
# abort the run. Print UTF-8 and degrade anything unsupported instead.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

FULL_INVOICE_TEXT = """บริษัท ปันปัน จำกัด
ใบกำกับภาษี / ใบเสร็จรับเงิน (ต้นฉบับ)
เลขที่ใบกำกับภาษี: IV68012207-09
วันที่ 07/12/2025
เลขประจำตัวผู้เสียภาษีอากร 0105567123468
ที่อยู่ 123 ถนนสุขุมวิท กรุงเทพฯ 10110

นามผู้ซื้อ บริษัท เอบีซี จำกัด
ที่อยู่ 456 ถนนพระราม 9 กรุงเทพฯ

รายการ                จำนวน   ราคา
สินค้า A                 1    2,000.00

รวมเป็นเงิน                  2,000.00
ภาษีมูลค่าเพิ่ม 7%              140.00
จำนวนเงินรวมทั้งสิ้น           2,140.00
"""

ABBREVIATED_RECEIPT_TEXT = """ร้านจรรยา
ใบเสร็จรับเงิน
วันที่ 23/07/2025
รวมทั้งสิ้น 1,050.00
ขอบคุณที่ใช้บริการ
"""

# Mirrors a real vendor invoice layout reported by a user, including two
# OCR quirks that tripped up earlier versions of the extractor:
#   1. "เลขที่เอกสาร" (a generic doc number) is printed ABOVE the real
#      "เลขที่ใบกำกับภาษี" field — a naive top-to-bottom scan grabs the
#      wrong one just because it appears first on the page.
#   2. The totals box gets OCR'd as a run of label lines followed by a run
#      of value lines (label column and value column read as separate
#      blocks) instead of one "label value" pair per line — same-line/
#      window matching then grabs the nearest number regardless of which
#      label it actually belongs to, making subtotal/VAT/total all resolve
#      to the same (wrong) figure.
# Also: "ชื่อลูกค้า : บริษัท A จำกัด" uses a colon separator, which used to
# leak a leading ":" into the extracted buyer name.
REAL_VENDOR_INVOICE_TEXT = """บริษัท รจนา จำกัด (สำนักงานใหญ่)
36/9 แขวงขุมทอง เขตลาดกระบัง กรุงเทพฯ 10250
เลขประจำตัวผู้เสียภาษี 0105558887774
โทร/แฟกซ์. 020-4567-902
ใบกำกับภาษี/ใบเสร็จรับเงิน
เลขที่เอกสาร INV6801015
ชื่อลูกค้า : บริษัท A จำกัด
ที่อยู่ : 99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร
กรุงเทพมหานคร 10900
เลขที่ใบกำกับภาษี IV0100168-99
วันที่ใบกำกับภาษี 01/01/68
สถานที่ส่งของ
ลำดับ รหัสสินค้า รายการ จำนวน หน่วย ราคา/หน่วย ส่วนลด จำนวนเงิน
1 001-001 ปากกาลูกลื่น (1*24) 1 กล่อง 135 0 135
2 001-004 กระดาษ (A4 80 แกรม 1*5) 2 ลัง 180 0 360
3 015-008 เครื่องคิดเลข 5 เครื่อง 370 0 1,850
4 020-004 แฟ้มใส่เอกสาร (A4) 30 แฟ้ม 80 0 2,400
หมายเหตุ
รวมเงิน
ส่วนลด
มูลค่าหลังส่วนลด
ภาษีมูลค่าเพิ่ม 7%
จำนวนเงินทั้งสิ้น
4,434.58
0.00
4,434.58
310.42
4,745.00
"""


# Mirrors a second real invoice reported by a user: a bilingual Thai/English
# receipt/tax-invoice where every field is printed as THREE lines (Thai
# label, English sub-label, then the value on its own line below) rather
# than "label value" on one line, plus a logo wordmark ("Moshi Moshi")
# printed above the real registered company name. The old extractor
# mis-parsed this as seller_name="Moshi", invoice_no="Document" (grabbed
# the English label word), buyer_name=empty, and subtotal/VAT/total all
# wrong.
BILINGUAL_INVOICE_TEXT = """Moshi
Moshi
บริษัท โมชิ โมชิ รีเทล คอร์ปอเรชั่น จำกัด (มหาชน)
เลขที่ 19 อาคารโลตัส สาขาคำเที่ยง ถนนมหาดค์เที่ยง ตำบลป่าตัน อำเภอเมืองเชียงใหม่
จังหวัดเชียงใหม่ 50300
เลขประจำตัวผู้เสียภาษี : 0107565000387 สาขาที่ 00141
ใบเสร็จรับเงิน/ใบกำกับภาษี
RECEIPT/TAX INVOICE
ชื่อผู้ซื้อ
Buyer Name
คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่
ที่อยู่
Buyer Address
239 ถ.ห้วยแก้ว สุเทพ เมือง เชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษี
Buyer Tax ID
0994000423179
เลขที่เอกสาร
Document No.
SI1412508004
วันที่เอกสาร
Document Date
02/08/2025
จำนวนเงิน
SUB TOTAL
2,812.00
ส่วนลดท้ายบิล
BILL DISCOUNT
2.00
จำนวนเงินหลังหักส่วนลด
AFTER DISCOUNT
2,626.17
ภาษีมูลค่าเพิ่ม 7%
VAT 7%
183.83
จำนวนเงินรวมสุทธิ
GRAND TOTAL AMOUNT
2,810.00
"""


# The ACTUAL raw OCR text a user pasted from the live app's "ดูข้อความ OCR
# ดิบ" viewer for the Moshi Moshi invoice (see BILINGUAL_INVOICE_TEXT above
# for context) — this is ground truth, not a guess, and is what finally
# revealed the real bugs:
#   - Every ำ in the OCR output is the decomposed NIKHAHIT+SARA-AA sequence
#     instead of the precomposed character, silently breaking every
#     keyword containing it ("จำนวน", "กำกับ", "จำกัด", ...).
#   - The document-info box (เลขที่เอกสาร / SI1412508004, etc.) is OCR'd as
#     ~10 label lines followed by the value lines — far past a 2-line
#     lookahead.
#   - The Thai buyer-name label got OCR'd as garbage ("ผู้ซี้ด"), and the
#     "Buyer Name" English sub-label ended up AFTER the value instead of
#     before it.
# Constructed with normal (precomposed) ำ below, then converted to the
# decomposed form the same way the real OCR output has it, so this test
# actually exercises normalize_thai_text().
REAL_MOSHI_RAW_TEXT = """Moshi
Moshi
BLBL
บริษัท โมชิ โมชิ รีเทล คอร์ปอเรชั่น จำกัด (มหาชน)
เลขที่ 19 อาคาร โลตัส สาขาคำเที่ยง ถนนตลาดคำเที่ยง ตำบลป่าตัน อำเภอเมืองเชียงใหม่
จังหวัดเชียงใหม่ 50300
เลขประจำตัวผู้เสียภาษี : 0107565000387 สาขาที่ 00141
Digtaly pred by u เลย คอร์ปอเรชั่น จำกัด (มหาชน)
Crit core L L โดย คอร์ปอเรชั่น จำกัด (มหาชน)
ใบเสร็จรับเงิน/ใบกำกับภาษี
RECEIPT/TAX INVOICE
ผู้ซี้ด
คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่
Buyer Name
สาขา
Buyer Branch ID.
รหัสผู้ซื้อ
ที่อยู่
Buyer Address
239 ถ.ห้วยแก้ว สุเทพ เมือง เชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษี
Buyer Tax ID.
0994000423179
สาขาที่ 00141
Buyer ID.
ลำดับ
NO.
1
รหัสสินค้า
PRODUCT CODE
ผู้ติดต่อ
รายการสินค้า/บริการ
DESCRIPTION
000000007100012598 ถุงหิ้ว size 18x36 นิ้ว
เบอร์โทรศัพท์ 053-942105
Buyer Contact Phone No.
เลขที่เอกสาร
Document No.
วันที่เอกสาร
Document Date
เลขที่เอกสารอ้างอิง
Document Ref.
วันที่เอกสารอ้างอิง
Date of Ref.
เลขที่ใบสั่งซื้อ
Purchase Order No.
SI1412508004
02/08/2025
000B141002000000272
02/08/2025
จำนวน
QUANTITY
ราคาต่อหน่วย
ส่วนลด
จำนวนเงินรวม
UNIT PRICE
ITEM DISCOUNT
TOTAL AMOUNT
1.00 EA
2.00
0.00
2.00
ชำระโดย
Paid by
วันครบกำหนดชำระเงิน
Payment Due Date
เครดิตเทอม
Payment Term
หมายเหตุ
Remark
*** เป็นการยกเลิกใบกำกับภาษีอย่างย่อเลขที่ 000B14100200000027202/08/2025 และออกใบกำกับภาษีอิเล็กทรอนิกส์ใหม่แทน ***
จำนวนเงิน
SUB TOTAL
ส่วนลดท้ายบิล
BILL DISCOUNT
จำนวนเงินหลังหักส่วนลด
AFTER DISCOINT
ภาษีมูลค่าเพิ่ม 7%
VAT 7%
จำนวนเงินรวมสุทธิ
2,812.00
2.00
2,626.17
183.83
2,810.00
GRAND TOTAL AMOUNT
"""
# Convert every precomposed ำ (U+0E33) above into the decomposed
# NIKHAHIT+SARA-AA sequence (U+0E4D U+0E32), matching the real OCR output.
REAL_MOSHI_RAW_TEXT = REAL_MOSHI_RAW_TEXT.replace("ำ", "ํา")


# Ways the buyer-name field (ชื่อลูกค้า / ชื่อผู้ซื้อ) comes out of Google
# Vision on a boxed Thai invoice. Google Vision reads a boxed layout
# column-major fairly often, which scatters a field's label away from its
# value and drops unrelated table cells in between — all of these used to
# return junk (a table line number, a salesperson code) or nothing.
_BUYER = "บริษัท A จำกัด"
BUYER_NAME_CASES = [
    (
        "label alone, items-table cells before the value",
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\nใบกำกับภาษี/ ใบเสร็จรับเงิน\n"
        "ชื่อลูกค้า :\nลำดับ\nรหัสสินค้า\n1\n001-001\nบริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "buyer box merged onto one line with the document box",
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\n"
        "ชื่อลูกค้า : บริษัท A จำกัด เลขที่ใบกำกับภาษี IV0100168-99\n"
        "ที่อยู่ : 99/15 ถนนวิภาวดีรังสิต วันที่ใบกำกับภาษี 01/01/68\n",
        _BUYER,
    ),
    (
        "whitespace-padded numeric cell right after the label",
        "บริษัท รจนา จำกัด\nชื่อลูกค้า\n  1\nบริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "รหัสลูกค้า (customer code) must not win over ชื่อลูกค้า",
        "บริษัท รจนา จำกัด\nรหัสลูกค้า 1\nชื่อลูกค้า : บริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "address line sits between the label and the name",
        "บริษัท รจนา จำกัด\nชื่อลูกค้า :\n"
        "ที่อยู่ : 99/15 ถนนวิภาวดีรังสิต แขวงจอมพล\nบริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "page marker and salesperson code as noise",
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\nหน้า 1/1\n"
        "ชื่อลูกค้า\n1/1\n001-H\nบริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "column-major read: page header lands between label and value",
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\n"
        "เลขประจำตัวผู้เสียภาษี 0105558887774\nใบกำกับภาษี/ ใบเสร็จรับเงิน\n"
        "ชื่อลูกค้า :\nที่อยู่ :\nเลขประจำตัวผู้เสียภาษี\n"
        "สาขาที่ออก ใบกำกับภาษี/ใบเสร็จรับเงิน : สำนักงานใหญ่\nหน้า 1/1\n"
        "บริษัท A จำกัด\n99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร\n"
        "กรุงเทพมหานคร 10900\n0105569123456\n",
        _BUYER,
    ),
    (
        "address lines sit under the label, the name is below them",
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\nใบกำกับภาษี/ ใบเสร็จรับเงิน\n"
        "ชื่อลูกค้า :\nที่อยู่ : 99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร\n"
        "กรุงเทพมหานคร 10900\nเลขประจำตัวผู้เสียภาษี 0105569123456\nบริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "value block emitted BEFORE the label block",
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\nใบกำกับภาษี/ ใบเสร็จรับเงิน\n"
        "บริษัท A จำกัด\n99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร\n"
        "กรุงเทพมหานคร 10900\n0105569123456\nชื่อลูกค้า :\nที่อยู่ :\n",
        _BUYER,
    ),
    (
        "an address line is never the buyer name",
        "บริษัท รจนา จำกัด\nชื่อลูกค้า :\nกรุงเทพมหานคร 10900\n",
        None,
    ),
    (
        "the seller's own name next to the label is not the buyer",
        "ใบกำกับภาษี/ ใบเสร็จรับเงิน\nชื่อลูกค้า :\n"
        "บริษัท รจนา จำกัด (สำนักงานใหญ่)\nบริษัท A จำกัด\n",
        _BUYER,
    ),
    (
        "no buyer field at all -> None, never a stray number",
        "ร้านจรรยา\nใบเสร็จรับเงิน\nวันที่ 23/07/2025\nรวมทั้งสิ้น 1,050.00\n",
        None,
    ),
]


# (label, (subtotal, vat, total) as extracted, expected after reconciling).
# The first case is the one reported from the live app.
TOTALS_CASES = [
    ("subtotal captured the VAT figure", (2571.03, 2571.03, 39300.00), (36728.97, 2571.03, 39300.00)),
    ("already consistent, left alone", (36728.97, 2571.03, 39300.00), (36728.97, 2571.03, 39300.00)),
    ("subtotal missing -> total - VAT", (None, 2571.03, 39300.00), (36728.97, 2571.03, 39300.00)),
    ("VAT missing -> total - subtotal", (36728.97, None, 39300.00), (36728.97, 2571.03, 39300.00)),
    ("total missing -> subtotal + VAT", (36728.97, 2571.03, None), (36728.97, 2571.03, 39300.00)),
    ("total captured the subtotal figure", (36728.97, 2571.03, 36728.97), (36728.97, 2571.03, 39300.00)),
    ("earlier invoice stays untouched", (4434.58, 310.42, 4745.00), (4434.58, 310.42, 4745.00)),
    ("unrepairable figures are left as read", (100.0, 55.0, 900.0), (100.0, 55.0, 900.0)),
    # an ใบย่อ legitimately has only a total — VAT must never be invented
    ("total only: VAT is not invented", (None, None, 1050.0), (None, None, 1050.0)),
]


# The ACTUAL raw OCR text pasted from the live app's "ดูข้อความ OCR ดิบ"
# viewer for the บริษัท รจนา invoice IV1400768-305 — ground truth, and the
# document that finally explained three rounds of wrong guesses about this
# layout. Google Vision reads this boxed form in an order nothing about the
# printed page predicts:
#   - The buyer name lands on the line ABOVE its own label, keeping the
#     colon separator (": บริษัท A จำกัด"), and the label line picks up a
#     stray "1" ("ชื่อลูกค้า : 1") — that "1" is what the app showed as the
#     buyer name. No amount of scanning FORWARD from the label could have
#     found the name; it isn't there.
#   - The totals column is scrambled the same way: 36,728.97 appears above
#     its "ราคารวมสินค้า (บาท)" label with "หมายเหตุ" in between, so a
#     forward search skipped it and returned the VAT figure below instead —
#     ยอดก่อนภาษี and VAT both came out 2,571.03.
#   - The document title is misread as "ใบทำกับภาษี" (not "ใบกำกับภาษี"), so
#     the เต็มรูป marker has to come from the "เลขที่ใบกำกับภาษี" field label.
#   - Quantity "10" is duplicated onto two lines, and the signature block at
#     the end is largely garbage ("Sgomfare").
REAL_ROJANA_RAW_TEXT = """R
บริษัท รจนา จำกัด (สำนักงานใหญ่)
36/9 แขวงขุมทอง เขตลาดกระบัง กรุงเทพฯ 10250
เลขประจำตัวผู้เสียภาษี 0105558887774
- โทร/แฟกซ์. 020-4567-902
: บริษัท A จำกัด
ชื่อลูกค้า : 1
สาขาที่ออก ใบกำกับภาษี/ใบเสร็จรับเงิน : สำนักงานใหญ่ หน้า 1/1
ใบทำกับภาษี/ใบเสร็จรับเงิน
ที่อยู่ : 99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร
กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษี 0105569123456
เลขที่ใบกำกับภาษี
IV1400768-305
วันที่ใบกำกับภาษี
14/07/68
ใบสั่งซื้อเลขที่
ใบสั่งขายเลขที่
วันครบกำหนด
ขนส่งโดย
รหัสพนักงานขาย
P-68777
S-22498
009-P
ลำดับ รหัสสินค้า
รายการ
จำนวน หน่วย ราคา/หน่วย ส่วนลด
จำนวนเงิน
1
002-009
ถุงขยะ(1*24ถุง)
10
10
แพ็ค
30
0
300
2
002-028
เก้าอี้สำนักงาน
5
ตัว
4,800
0
24,000
3
002-044
หมึกเครื่องพิมพ์ HP
12
กล่อง
1,250
0
15,000
36,728.97
หมายเหตุ
ราคารวมสินค้า (บาท)
ภาษีมูลค่าเพิ่ม 7%
2,571.03
(สามหมื่นเก้าพันสามร้อยบาทถ้วน)
จำนวนเงินทั้งสิ้น (บาท)
39,300.00
ได้รับสินค้าตามที่ระบุไว้ครบถ้วนแล้ว
ในนามสำนักงานใหญ่
ชำาระโดย
ผู้จ่ายของ
เงินสด
เช็ค
- เงินโอน
Sgomfare
ผู้ตรวจสอบ
เช็คธนาคาร
เลขที่เช็ค
ลงนามผู้รับของ
ผู้มีอำนาจลงนาม
วันที่
วันที่
ผู้ส่งของ
วันที่บนเช็ค
ผู้รับเช็ค
"""


# Raw OCR text from the live app for the JP invoice IV6800413-039 — ground
# truth. The extractor found no amounts at all on this one, for two reasons:
#   - Every figure is printed in the Thai whole-baht shorthand ("1,300.-",
#     "91.-", "1,391.-"), which parsed as no number at all.
#   - The totals figures are separated from their labels by the entire
#     payment-method and signature block — eight lines — so the label/value
#     pairing gave up long before reaching them.
# Also here: a bilingual "ชื่อลูกค้า/Customer Name :" label, a "รหัสลูกค้า/
# Customer Code : 7820-12" field that must not be mistaken for the buyer,
# and OCR dropping ำ in several words ("ล่าดับ", "การชาระเงิน", "ผู้มีอานาจ").
REAL_JP_RAW_TEXT = """JP
บริษัท โจธนารักษ์ แพตเดอร์สัน จำกัด (สำนักงานใหญ่)
123/69 ถนนฉลองกรุง แขวงลาดกระบัง เขตลาดกระบัง กรุงเทพฯ 10520
เลขประจำตัวผู้เสียภาษี 0105576890143
โทร. 020-5345-678 /แฟกซ์. 026-9267-00
ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด
ที่อยู่/Address : 99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษี/TAX ID : 0105569123456
เลขที่ใบสั่งชื้อ/Order No.
พนักงานขาย/Salesman
กำหนดชาระ/Due Date
ใบกำกับภาษี/ใบเสร็จรับเงิน
TAX INVOICE/RECEIPT
เลขที่/No.
วันที่/Date.
**ต้นฉบับ/Original**
IV6800413-039
13/04/68
รหัสลูกค้า/Customer Code : 7820-12
ล่าดับ
1.
ออกแบบผลิตภัณฑ์
หมายเหตุ
000
รายการ
จำนวน
ราคา
ราคาสุทธิ
1
1,300.-
1,300.-
ราคารวมสินค้า (บาท)
ภาษีมูลค่าเพิ่ม (VAT) 7%
(หนึ่งพันสามร้อยเก้าสิบเอ็ด)
จำนวนเงินทั้งสิ้น (บาท)
การชาระเงิน/Payment
เงินสด Cash
โอนเข้าบัญชี Tater.No..
เช็ค/Chegue.No..
วันที่/Date
ในนามบริษัท โจธนารักษ์ แพตเดอร์สัน จำกัด
ผู้มีอานาจลงนาม
.....................
1,300.-
91.-
1,391.-
ลงนามพนักงานรับเงิน
(วันที
ลงนามพนักงานส่งของ
......................
"""


# Raw OCR text from the live app for the บาบาร่า invoice IV20250123-089 —
# ground truth. All three amounts were wrong or missing, from two causes:
#   - Vision dropped the MAI THO from the grand-total label, reading
#     "ราคารวมทั้งสิน" for "ราคารวมทั้งสิ้น". That matched no keyword, so the
#     totals block had 2 labels against 3 values and refused to pair.
#   - Falling back to keyword search, the last-resort subtotal keyword
#     "จำนวนเงิน" matched the items-table's own column heading (alone on its
#     line in a column-major read) and took the row number "1" below it.
# VAT then came from the line after its label — the SUBTOTAL's value.
REAL_BARBARA_RAW_TEXT = """บริษัท บาบาร่า จำกัด (สำนักงานใหญ่)
248/69 อาคารเฉลิมชัย ถนนรามคำแหง
แขวงสวนหลวง กรุงเทพมหานคร 10250
เลขประจำตัวผู้เสียภาษี 0153789056112
โทร/แฟกซ์. 0-2719-367-01
สาขาที่
JB
ใบกำกับภาษี/ใบเสร็จรับเงิน
TAXINVOICE/RECEIPT
เลขที่
IV20250123-089
ชื่อลูกค้า : บริษัท A จำกัด
:
ที่อยู่ : 9/15 ถนนวิภาวดีรังสิต แขวงจอมพล
เขตจตุจักร กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษี 0105569123456
ต้นฉบับ-ลูกค้า
วันที่
22/01/2025
ลำดับที่
รายการ
จำนวน
ราคา/หน่วย
จำนวนเงิน
1
น้ำมันพืช (1.5L)
5
48
240
2
ปลากระป๋อง (1*24 กป)
1
120
120
หมายเหตุ
ราคารวมสินค้า (บาท)
ภาษีมูลค่าเพิ่ม/VAT
ราคารวมทั้งสิน (บาท)
336.45
23.55
360.00
ในนามบริษัท บาบาร่า จำกัด
ชำระเงินโดย เงินสด ( โอน O เช็ค
(ลายเซ็นผู้ส่งของ)
(ลายเซ็นผู้ส่งของ)
(ผู้มีอำนาจลงนาม)
วันที่
วันที่
วันที่
"""


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    return cond


def main():
    all_ok = True

    fields = extractor.extract_fields(FULL_INVOICE_TEXT, ocr_confidence=92.0)
    print("\n--- Full invoice fields ---")
    for k, v in fields.items():
        print(f"  {k}: {v}")
    all_ok &= check("invoice_no extracted", fields["invoice_no"] == "IV68012207-09")
    all_ok &= check("date parsed to ISO", fields["invoice_date_iso"] == "2025-12-07")
    all_ok &= check("seller tax id extracted", fields["seller_tax_id"] == "0105567123468")
    all_ok &= check("buyer name extracted", fields["buyer_name"] is not None)
    all_ok &= check("vat = 140.0", fields["vat"] == 140.0)
    all_ok &= check("total = 2140.0", fields["total"] == 2140.0)
    all_ok &= check("classified as เต็มรูป", fields["doc_type"] == "เต็มรูป")
    all_ok &= check("not flagged for review", fields["needs_review"] is False)

    fields2 = extractor.extract_fields(ABBREVIATED_RECEIPT_TEXT, ocr_confidence=80.0)
    print("\n--- Abbreviated receipt fields ---")
    for k, v in fields2.items():
        print(f"  {k}: {v}")
    all_ok &= check("classified as ย่อ", fields2["doc_type"] == "ย่อ")
    all_ok &= check("total = 1050.0", fields2["total"] == 1050.0)
    all_ok &= check("flagged for review (missing tax id/invoice no)", fields2["needs_review"] is True)

    all_ok &= check("13-digit tax id format accepted", extractor.has_valid_tax_id_format("0105567123469"))
    all_ok &= check("12-digit (too short) tax id rejected", extractor.has_valid_tax_id_format("010556712346") is False)

    # regression: real vendor invoice with "เลขที่เอกสาร" printed above the
    # real "เลขที่ใบกำกับภาษี", a colon-separated buyer name, and a
    # column-major totals box (see comment on REAL_VENDOR_INVOICE_TEXT)
    fields3 = extractor.extract_fields(REAL_VENDOR_INVOICE_TEXT, ocr_confidence=88.0)
    print("\n--- Real vendor invoice fields ---")
    for k, v in fields3.items():
        print(f"  {k}: {v}")
    all_ok &= check("real invoice: invoice_no = IV0100168-99 (not INV6801015)", fields3["invoice_no"] == "IV0100168-99")
    all_ok &= check("real invoice: buyer_name has no leading colon", fields3["buyer_name"] == "บริษัท A จำกัด")
    all_ok &= check("real invoice: subtotal = 4434.58", fields3["subtotal"] == 4434.58)
    all_ok &= check("real invoice: vat = 310.42 (not 4434.58)", fields3["vat"] == 310.42)
    all_ok &= check("real invoice: total = 4745.0 (not 4434.58)", fields3["total"] == 4745.0)

    # regression: bilingual 3-line-per-field invoice with a logo wordmark
    # above the real company name (see comment on BILINGUAL_INVOICE_TEXT)
    fields4 = extractor.extract_fields(BILINGUAL_INVOICE_TEXT, ocr_confidence=85.0)
    print("\n--- Bilingual invoice fields ---")
    for k, v in fields4.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "bilingual: seller_name is the registered company name (not 'Moshi')",
        fields4["seller_name"] == "บริษัท โมชิ โมชิ รีเทล คอร์ปอเรชั่น จำกัด (มหาชน)",
    )
    all_ok &= check(
        "bilingual: invoice_no = SI1412508004 (not 'Document')",
        fields4["invoice_no"] == "SI1412508004",
    )
    all_ok &= check(
        "bilingual: buyer_name extracted (not empty)",
        fields4["buyer_name"] == "คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่",
    )
    all_ok &= check("bilingual: invoice_date_iso = 2025-08-02 (not truncated)", fields4["invoice_date_iso"] == "2025-08-02")
    all_ok &= check("bilingual: subtotal = 2626.17 (post-discount)", fields4["subtotal"] == 2626.17)
    all_ok &= check("bilingual: vat = 183.83 (not 2812)", fields4["vat"] == 183.83)
    all_ok &= check("bilingual: total = 2810.0 (not 1)", fields4["total"] == 2810.0)

    # regression: the ACTUAL raw OCR text from the live app for the Moshi
    # Moshi invoice (see comment on REAL_MOSHI_RAW_TEXT) — ground truth,
    # not a guess
    fields5 = extractor.extract_fields(REAL_MOSHI_RAW_TEXT, ocr_confidence=85.0)
    print("\n--- Real Moshi Moshi OCR text fields ---")
    for k, v in fields5.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real moshi: seller_name is the registered company name",
        fields5["seller_name"] == "บริษัท โมชิ โมชิ รีเทล คอร์ปอเรชั่น จำกัด (มหาชน)",
    )
    all_ok &= check(
        "real moshi: invoice_no = SI1412508004 (not '50300' postal code)",
        fields5["invoice_no"] == "SI1412508004",
    )
    all_ok &= check(
        "real moshi: buyer_name extracted (not 'สาขา')",
        fields5["buyer_name"] == "คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่",
    )
    all_ok &= check("real moshi: subtotal = 2626.17 (post-discount)", fields5["subtotal"] == 2626.17)
    all_ok &= check("real moshi: vat = 183.83 (not 2812)", fields5["vat"] == 183.83)
    all_ok &= check("real moshi: total = 2810.0 (not 1)", fields5["total"] == 2810.0)

    # regression: the ACTUAL raw OCR text from the live app for the รจนา
    # invoice (see comment on REAL_ROJANA_RAW_TEXT) — ground truth. Every
    # field has to come out right from text whose line order matches nothing
    # about how the page is printed.
    fields6 = extractor.extract_fields(REAL_ROJANA_RAW_TEXT, ocr_confidence=88.0)
    print("\n--- Real รจนา OCR text fields ---")
    for k, v in fields6.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real rojana: buyer_name = บริษัท A จำกัด (value sits ABOVE its label, not '1')",
        fields6["buyer_name"] == "บริษัท A จำกัด",
    )
    all_ok &= check(
        "real rojana: subtotal = 36728.97 read from the page (not the VAT figure)",
        fields6["subtotal"] == 36728.97,
    )
    all_ok &= check("real rojana: vat = 2571.03", fields6["vat"] == 2571.03)
    all_ok &= check("real rojana: total = 39300.0", fields6["total"] == 39300.0)
    all_ok &= check(
        "real rojana: amounts balance", fields6["subtotal"] + fields6["vat"] == fields6["total"]
    )
    all_ok &= check("real rojana: invoice_no = IV1400768-305", fields6["invoice_no"] == "IV1400768-305")
    all_ok &= check("real rojana: date = 2025-07-14", fields6["invoice_date_iso"] == "2025-07-14")
    all_ok &= check(
        "real rojana: seller = บริษัท รจนา จำกัด (สำนักงานใหญ่)",
        fields6["seller_name"] == "บริษัท รจนา จำกัด (สำนักงานใหญ่)",
    )
    all_ok &= check("real rojana: seller tax id", fields6["seller_tax_id"] == "0105558887774")
    all_ok &= check("real rojana: classified เต็มรูป", fields6["doc_type"] == "เต็มรูป")
    all_ok &= check("real rojana: not flagged for review", fields6["needs_review"] is False)

    # regression: the ACTUAL raw OCR text for the JP invoice (see comment on
    # REAL_JP_RAW_TEXT) — amounts in Thai "1,300.-" shorthand, printed far
    # away from their labels. The app showed all three amount fields empty.
    fields7 = extractor.extract_fields(REAL_JP_RAW_TEXT, ocr_confidence=92.0)
    print("\n--- Real JP OCR text fields ---")
    for k, v in fields7.items():
        print(f"  {k}: {v}")
    all_ok &= check("real jp: subtotal = 1300.0 (was empty)", fields7["subtotal"] == 1300.0)
    all_ok &= check("real jp: vat = 91.0 (was empty)", fields7["vat"] == 91.0)
    all_ok &= check("real jp: total = 1391.0 (was empty)", fields7["total"] == 1391.0)
    all_ok &= check(
        "real jp: buyer_name = บริษัท เอ จำกัด (not the Customer Code)",
        fields7["buyer_name"] == "บริษัท เอ จำกัด",
    )
    all_ok &= check("real jp: invoice_no = IV6800413-039", fields7["invoice_no"] == "IV6800413-039")
    all_ok &= check("real jp: date = 2025-04-13", fields7["invoice_date_iso"] == "2025-04-13")
    all_ok &= check("real jp: seller tax id", fields7["seller_tax_id"] == "0105576890143")
    all_ok &= check("real jp: classified เต็มรูป", fields7["doc_type"] == "เต็มรูป")
    all_ok &= check("real jp: not flagged for review", fields7["needs_review"] is False)

    # the "1,300.-" whole-baht shorthand, on its own
    all_ok &= check("'1,300.-' parses as 1300.0", extractor._clean_number("1,300.-") == 1300.0)
    all_ok &= check("'91.-' parses as 91.0", extractor._clean_number("91.-") == 91.0)
    all_ok &= check("'1,300,-' parses as 1300.0", extractor._clean_number("1,300,-") == 1300.0)
    all_ok &= check("'2,571.03' still parses", extractor._clean_number("2,571.03") == 2571.03)
    all_ok &= check("'-50.00' is still negative", extractor._clean_number("-50.00") == -50.0)

    # regression: the ACTUAL raw OCR text for the บาบาร่า invoice (see comment
    # on REAL_BARBARA_RAW_TEXT) — a dropped tone mark on the grand-total
    # label plus an items-table column heading posing as a subtotal label.
    fields8 = extractor.extract_fields(REAL_BARBARA_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real บาบาร่า OCR text fields ---")
    for k, v in fields8.items():
        print(f"  {k}: {v}")
    all_ok &= check("real barbara: subtotal = 336.45 (not 1)", fields8["subtotal"] == 336.45)
    all_ok &= check("real barbara: vat = 23.55 (not 336.45)", fields8["vat"] == 23.55)
    all_ok &= check("real barbara: total = 360.0 (was missing)", fields8["total"] == 360.0)
    all_ok &= check("real barbara: buyer_name", fields8["buyer_name"] == "บริษัท A จำกัด")
    all_ok &= check("real barbara: invoice_no", fields8["invoice_no"] == "IV20250123-089")
    all_ok &= check("real barbara: date = 2025-01-22", fields8["invoice_date_iso"] == "2025-01-22")
    all_ok &= check("real barbara: classified เต็มรูป", fields8["doc_type"] == "เต็มรูป")
    all_ok &= check("real barbara: not flagged for review", fields8["needs_review"] is False)

    # a dropped tone mark on ทั้งสิ้น must not hide the grand total
    all_ok &= check(
        "'ราคารวมทั้งสิน' (no tone mark) still classifies as the total",
        extractor._classify_totals_label("ราคารวมทั้งสิน (บาท)") == "total",
    )
    all_ok &= check(
        "'ราคารวมทั้งสิ้น' (correct spelling) classifies as the total",
        extractor._classify_totals_label("ราคารวมทั้งสิ้น (บาท)") == "total",
    )

    # a bare "จำนวนเงิน" among other column headings is a table heading;
    # standing alone next to its own figure it is still a subtotal label
    header_lines = ["ลำดับที่", "รายการ", "จำนวน", "ราคา/หน่วย", "จำนวนเงิน", "1"]
    all_ok &= check(
        "bare 'จำนวนเงิน' in a column-heading run is a table header",
        extractor._is_table_column_header(header_lines, 4),
    )
    all_ok &= check(
        "'จำนวนเงิน' with its own value is NOT a table header",
        extractor._is_table_column_header(["หมายเหตุ", "จำนวนเงิน 2,000.00", "ภาษี"], 1) is False,
    )

    # regression: buyer name (ชื่อผู้ซื้อ). Reported from the live app on the
    # รจนา invoice — the ชื่อผู้ซื้อ box came out as "1", i.e. a cell from the
    # items table instead of the ชื่อลูกค้า value. Each case below is a way a
    # boxed Thai invoice gets OCR'd that used to yield junk or nothing.
    print("\n--- Buyer name edge cases ---")
    for label, text, expected in BUYER_NAME_CASES:
        got = extractor.extract_buyer_name(text, seller_name=extractor.extract_seller_name(text))
        print(f"  {label}: {got!r}")
        all_ok &= check(f"buyer name — {label}", got == expected)

    # a missing buyer name silently downgrades a full ใบกำกับภาษี to ย่อ
    # (VAT not deductible), so it has to show up as a review reason
    no_buyer = extractor.extract_fields(
        "บริษัท รจนา จำกัด\nใบกำกับภาษี/ใบเสร็จรับเงิน\n"
        "เลขประจำตัวผู้เสียภาษี 0105558887774\nเลขที่ใบกำกับภาษี IV0100168-99\n"
        "วันที่ 01/01/68\nรวมทั้งสิ้น 4,745.00\n",
        ocr_confidence=90.0,
    )
    all_ok &= check(
        "missing buyer name is flagged for review",
        no_buyer["needs_review"] and "ชื่อผู้ซื้อ" in (no_buyer["review_reason"] or ""),
    )

    # regression: ยอดก่อนภาษี / VAT / ยอดรวม must agree with each other.
    # Reported from the live app — an invoice came back with ยอดก่อนภาษี and
    # VAT both showing 2,571.03 against a 39,300.00 total, i.e. the same
    # figure captured twice. The three amounts are not independent, so the
    # arithmetic identifies which one is wrong on its own.
    print("\n--- Totals reconciliation ---")
    for label, amounts, expected in TOTALS_CASES:
        got = extractor.reconcile_totals(*amounts)
        print(f"  {label}: {amounts} -> {got[:3]}")
        all_ok &= check(f"totals — {label}", got[:3] == expected)

    # an invoice whose amounts can't be reconciled must be flagged, not
    # silently recorded with figures that don't add up
    broken = extractor.extract_fields(
        "บริษัท รจนา จำกัด\nใบกำกับภาษี/ใบเสร็จรับเงิน\n"
        "เลขประจำตัวผู้เสียภาษี 0105558887774\nเลขที่ใบกำกับภาษี IV1400768-305\n"
        "ชื่อลูกค้า : บริษัท A จำกัด\nวันที่ 14/07/68\n"
        "รวมเป็นเงิน 100.00\nภาษีมูลค่าเพิ่ม 7% 55.00\nรวมทั้งสิ้น 900.00\n",
        ocr_confidence=90.0,
    )
    all_ok &= check(
        "amounts that don't add up are flagged for review",
        broken["needs_review"] and "ยอดไม่สอดคล้องกัน" in (broken["review_reason"] or ""),
    )
    print(f"  warning text: {broken['review_reason']}")

    # the warning names the actual figures, including what the VAT should be
    all_ok &= check(
        "warning states the VAT that was read and the 7% figure expected",
        extractor.totals_mismatch_reason(1900.0, 140.0, 2040.0)
        == "⚠️ ยอดไม่สอดคล้องกัน: VAT ที่ระบุ (140 บาท) ไม่ตรงกับ 7% ของยอดก่อนภาษี "
           "(ควรเป็น 133 บาท) — โปรดตรวจสอบ",
    )
    all_ok &= check(
        "warning when the three don't add up",
        extractor.totals_mismatch_reason(2000.0, 140.0, 2500.0)
        == "⚠️ ยอดไม่สอดคล้องกัน: ยอดก่อนภาษี + VAT (2,140 บาท) ไม่เท่ากับยอดรวม "
           "(2,500 บาท) — โปรดตรวจสอบ",
    )
    all_ok &= check(
        "consistent amounts produce no warning",
        extractor.totals_mismatch_reason(2000.0, 140.0, 2140.0) is None,
    )

    # regression: an invoice read correctly whose ยอดรวม OCR missed. The
    # total is derived and checks out, so the record must come back CLEAN —
    # a derived-but-verified figure is not something to warn about.
    derived_total = extractor.extract_fields(
        "บริษัท โจธนารักษ์ แพตเดอร์สัน จำกัด (สำนักงานใหญ่)\n"
        "เลขประจำตัวผู้เสียภาษี 0105576890143\nใบกำกับภาษี/ใบเสร็จรับเงิน\n"
        "ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด\n"
        "เลขที่ใบกำกับภาษี IV6800107-054\nวันที่ 07/01/68\n"
        "ราคารวมสินค้า (บาท) 2,000.-\nภาษีมูลค่าเพิ่ม (VAT) 7% 140.-\n",
        ocr_confidence=92.0,
    )
    all_ok &= check(
        "derived total, everything consistent -> no review flag",
        derived_total["needs_review"] is False and derived_total["total"] == 2140.0,
    )
    all_ok &= check(
        "bilingual label remnant stripped from buyer name",
        derived_total["buyer_name"] == "บริษัท เอ จำกัด",
    )

    # multi-invoice split
    combined = FULL_INVOICE_TEXT + "\n" + FULL_INVOICE_TEXT
    chunks = extractor.split_multi_invoice_text(combined)
    all_ok &= check("multi-invoice split into 2 chunks", len(chunks) >= 2)

    # regression: a SINGLE invoice contains the word "ใบกำกับภาษี" multiple
    # times (title line + "เลขที่ใบกำกับภาษี:" field label line) — must NOT
    # be split into multiple records just because the word repeats
    single_chunks = extractor.split_multi_invoice_text(FULL_INVOICE_TEXT)
    all_ok &= check(
        "single invoice with repeated keyword stays as 1 chunk",
        len(single_chunks) == 1,
    )

    print("\n" + ("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
