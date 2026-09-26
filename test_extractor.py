"""Unit tests for extractor.py that don't require a real OCR/Tesseract run.

These feed in text that approximates what Tesseract would output for a
Thai tax invoice, so we can validate the regex/field-extraction logic on
its own. Run: python3 test_extractor.py
"""
import re
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


# Raw OCR text from the live app for the second บาบาร่า invoice
# IV20250504-012 — ground truth. Everything read correctly EXCEPT the
# invoice number, which came out "IV20250504": the number sits 50
# characters after its bare "เลขที่" label (the branch/title lines are
# emitted in between), and the keyword fallback's 60-character window ended
# in the middle of it, so the truncated half was recorded as the value.
REAL_BARBARA2_RAW_TEXT = """บริษัท บาบาร่า จำกัด (สำนักงานใหญ่)
248/69 อาคารเฉลิมชัย ถนนรามคำแหง
แขวงสวนหลวง กรุงเทพมหานคร 10250
เลขประจำตัวผู้เสียภาษี 0153789056112
โทร/แฟกซ์. 0-2719-367-01
สาขาที่
เลขที่
GB
ใบกำกับภาษี/ใบเสร็จรับเงิน
TAXINVOICE/RECEIPT
IV20250504-012
ชื่อลูกค้า : บริษัท A จำกัด
ที่อยู่ : 9/15 ถนนวิภาวดีรังสิต แขวงจอมพล
เขตจตุจักร กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษี 0105569123456
ต้นฉบับ-ลูกค้า
วันที่
24/05/2025
ลำดับที่
1
แฟ้มใส่เอกสาร (A4)
2
รายการ
กล่องใส่ของ (100*100*100 นิ้ว)
จำนวน
ราคา/หน่วย
จำนวนเงิน
20
60
1,200
LO
5
365
1,825
หมายเหตุ
ราคารวมสินค้า (บาท)
ภาษีมูลค่าเพิ่ม/VAT
ราคารวมทั้งสิ้น (บาท)
2,827.10
197.90
3,025.00
ในนามบริษัท บาบาร่า จำกัด
ชำระเงินโดย เงินสด ( โอน O เช็ค
(ลายเซ็นผู้ส่งของ)
(ลายเซ็นผู้ส่งของ)
(ผู้มีอำนาจลงนาม)
วันที่
วันที่
วันที่
"""


# Raw OCR text from the live app for the มั่งมีศรีสุข invoice INV-2568-01 —
# ground truth, and the worst one so far: four independent failures at once.
#   - OCR wrote the decimal points as COMMAS ("15,750,00", "1,102,50"), so
#     stripping thousands separators inflated every amount a hundredfold.
#   - This invoice separates VATable from exempt goods, and BOTH labels
#     ("สินค้าที่เสียภาษีมูลค่าเพิ่ม", "สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม") contain the
#     word VAT, so both classified as the VAT amount.
#   - "รวมมูลค่าสุทธิ" (net total) and "หัก เงิน จ๋า" (a garbled deposit
#     deduction) matched nothing, breaking the label run.
#   - The number label lost its tone mark ("เลขที / NO") and its value sits
#     seven lines away in a column-major box, so no invoice number was
#     found at all — which alone downgraded a full tax invoice to ใบย่อ and
#     wiped its subtotal and VAT.
REAL_MUNGMEE_RAW_TEXT = """มศส
เลขประจำตัวผู้เสียภาษีอากร
0105568000222
บริษัท มั่งมีศรีสุข จำกัด (สำนักงานใหญ่)
MUNGMEE SRISUK CO., LTD. (Head Office)
88/8 อาคารมั่งมีศรีสุข ชั้น 12 ถนนรัชดาภิเษก แขวงห้วยขวาง เขตห้วยขวาง กรุงเทพมหานคร 10310
88/8 Mungmee Srisuk Building, 12th Floor, Ratchadaphisek Rd., Huai Khwang, Bangkok 10310
โทร./Tel. 02-988-1234 E-mail : sales@mungmeesrisuk.example
ใบเสร็จรับเงิน / ใบกำกับภาษี
RECEIPT / TAX INVOICE
งวดประจำเดือนมกราคม 2568
นามผู้ชื้อ / Name
บริษัท A จำกัด
ที่อยู่ / Address
99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษีอากร / Tax ID
0105569123456
เลขที / NO
วันที่ / DATE
เครดิต / CREDIT
วันครบกำาหนด/DUE DATE
เลขที่ใบสั่งซื้อ / PO.NO
พนักงานขาย / SALEMAN
รหัสลูกค้า / CUSTOMER
INV-2568-01
31/01/2568
30 วัน
02/03/2568
PO-2568-0105
สมหญิง รักงาน
CUS-0088
าบที
ITEM
รายการ
DESCRIPTION
จำนวน
หน่วยนับ
ราคาต่อหน่วย
ส่วนลดต่อหน่วย
V/N*
QUANTITY
UNIT
UNIT PRICE
DISCOUNT
1
ชุดกระเช้าของขวัญปีใหม่
2
การ์ดอวยพรปีใหม่
หมายเหตุ * (V ภาษีมูลค่าเพิ่ม / N ยกเว้นภาษีมูลค่าเพิ่ม)
จำนวนเงินรวม (ตัวอักษร)
GRAND TOTAL (ALPHABET)
V
ท
15
เช็ต
890.00
40.00
หน้าที่ 1/1
จำนวนเงินบาท
AMOUNT (BAHT)
12,750.00
V
200
ไป
15.00
0,00
3,000,00
หนึ่งหมื่นหกพันแปดร้อยห้าสิบสองบาทห้าสิบสตางค์
- สินค้าตามใบกำกับภาษีนี้ แม้จะส่งมอบแก่ผู้ซื้อแล้วก็ยังคงเป็นทรัพย์สินของผู้ขายจนกว่าผู้ซื้อได้ชำระเงินเรียบร้อยแล้ว
- โปรดสั่งจ่ายเช็คขีดคร่อมในนาม "บริษัท มั่งมีศรีสุข จำกัด" เท่านั้น
- การชำระเงินด้วยเช็คจะสมบูรณ์ต่อเมื่อได้รับเงินตามเช็คเรียบร้อยแล้ว
- ถ้าสินค้าไม่ถูกต้องโปรดแจ้งกลับภายใน 7 วัน หากเกินกำหนดทางบริษัทขอสงวนสิทธิ์ในการเปลี่ยนหรือคืน
ราคาพิเศษช่วงปีใหม่ สินค้าตามรายการนี้ไม่รับเปลี่ยนคืนหลังวันที่ 15 มกราคม
สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม
สินค้าที่เสียภาษีมูลค่าเพิ่ม
ภาษีมูลค่าเพิ่ม VAT7%
หัก เงิน จ๋า
รวมมูลค่าสุทธิ
บริษัท มั่งมีศรีสุข จำกัด
gA
ผู้มีอานาจลงนาม
AUTHORIZED SIGNATURE
0.00
15,750,00
1,102,50
0.00
16,852.50
"""


# Raw OCR text from the live app for the ร่ำรวย888 invoice RE00001 —
# ground truth. Five fields were wrong, from four separate causes:
#   - Every amount carries its currency ("183,800.00 บาท"), so no line in
#     the totals column registered as a number and the box paired nothing.
#   - The box ends with "จำนวนเงินรวมทั้งสิ้น" AND a summary row
#     "จำนวนรวมทั้งสิ้น" — two Thai labels classifying alike, which the
#     bilingual-label collapse merged into one, shifting every figure.
#   - There is no invoice-number label at all: the number is printed under
#     the title. The bare "เลขที่" keyword instead matched "เลขที่บัญชี" and
#     filed the seller's BANK ACCOUNT as the invoice number.
#   - "วันที่" in the signature block ("ผู้สั่งซื้อสินค้า / วันที่ 21/01/2558")
#     was read as the document's date.
REAL_ROMRUAY_RAW_TEXT = """8
บริษัท ร่ำรวย888 จำกัด
289 อาคารร่ำรวย888 ทาวเวอร์ ชั้น 18 ถนนเพชรบุรีตัดใหม่
แขวงบางกะปิ เขตห้วยขวาง กรุงเทพมหานคร 10310
เลขประจำตัวผู้เสียภาษีอากร 0105568345671
โทร. 02-777-8899 อีเมล sales prommay888.example
เว็บไซต์ www.romruay888.example
ชื่อลูกค้า
ชื่อนิติบุคคล
ที่อยู่
เลขประจำตัวผู้เสียภาษี
เบอร์โทรศัพท์
อีเมล
กิตติพงษ์ วิริยะกุล
บริษัท A จำกัด
99/15 ถนนวิภาวดีรังสิต แขวงจอมพล
เขตจตุจักร กรุงเทพมหานคร 10900
0105569123456
089-123-4567
purchasing@companya.example
ชื่อผู้ชาย
เบอร์ติดต่อ
ชื่อโปรเจกต์
ไม้และวัสดุก่อสร้างสำหรับโครงการรีสอร์ทริมทะเล
เลขที่อ้างอิง
วันที่ออกใบนัดจ่า
วันที่ครบก้าหนด
ล่าดับ รายการสินค้า
ไม้สัก
1
2
เกรด A
ไม้สะเดา
เกรด A
ช่องทางการชาระเงิน
หมายเหตุ -
ธนาคาร
เลขที่บัญชี
ชื่อบัญชี
หรือสแกนเพื่อชำระเงิน (ตัวอย่าง)
กสิกรไทย
456-7-89012-3
บริษัท ร่ำรวย888 จำกัด
หน้า 1/1
ต้นฉบับ (เอกสารออกเป็นชุด)
ใบกำกับภาษี/ใบเสร็จ
RE00001
มั่งมี ทรัพย์เจริญ
081-888-8888
REF-2568-01
31/01/2568
07/02/2568
จำนวน
หน่วย
ราคา/หน่วย
ส่วนลด
ยอดรวม
80
ลูกบาศก์ฟุต
2,200,00
0.00
176,000.00
60
ลูกบาศก์ฟุต
130.00
0.00
7,800.00
ยอดรวม
ส่วนลดเพิ่มเติม
ยอดรวมหลังหักส่วนลด
ภาษีมูลค่าเพิ่ม (7%)
จำนวนเงินรวมทั้งสิ้น
จำนวนรวมทั้งสิ้น
183,800.00 บาท
3,800.00 บาท
180,000.00 บาท
12,600.00 บาท
192,600.00 บาท
192,600.00
kin
ผู้สั่งซื้อสินค้า
วันที่ 21/01/2558
ผู้อนุมัติ
วันที่ 30/01/2558
"""


# Raw OCR text from the live app for the ฟาร์มเงินฟาร์มทอง invoice
# INV-2568-001 — ground truth. The amounts came out right; the two NAMES
# were wrong, and for linked reasons:
#   - Vision emitted the customer box's entire label column first —
#     "ชื่อลูกค้า", "Customer Name", "ที่อยู่", ... twelve lines — before the
#     letterhead. The seller search only looked at the first eight lines,
#     found no company name there, and its fallback returned the bare label
#     "ชื่อลูกค้า" as the seller.
#   - With the seller misidentified, the buyer search's "the buyer is never
#     the seller" guard had nothing real to compare against, so it took the
#     seller's own name as the buyer. Fixing the seller alone was not
#     enough either: the letterhead repeats the name in English on the next
#     line ("FARM NGERN FARM THONG CO., LTD."), and that twin was then
#     picked instead.
REAL_FARM_RAW_TEXT = """ชื่อลูกค้า
Customer Name
ที่อยู่
Address
เลขประจำตัวผู้เสียภาษีอากร
Tax Identification
โทร.Tel.
ล่าดับที
1
2
เลขที่ใบสั่งชื้อ
PIO No.
บริษัท ฟาร์มเงินฟาร์มทอง จำกัด
FARM NGERN FARM THONG CO., LTD.
55/2 หมู่ 3 ตำาบลบางเลน อำเภอบางเลน จังหวัดนครปฐม 73130
55/2 Moo 3, Bang Len, Nakhon Pathom 73130
Tel. 034-991-234 Email: contact@ngernthongfarm.example
เลขประจำตัวผู้เสียภาษีอากร 0173568002246 (สำนักงานใหญ่)
ต้นฉบับใบกำกับภาษี/ใบส่งสินค้า
ORIGINAL TAX INVOICE / DELIVERY ORDER
สำหรับลูกค้า / CUSTOMER
เอกสารออกเป็นชุด
บริษัท A จำกัด
เลขที
INV-2568-001
99/15 ถนนวิภาวดีรังสิต
วันที
31/01/2568
แขวงจอมพล เขตจตุจักร
Date
กรุงเทพมหานคร 10900
พนักงานขาย
Salesman
สมพงษ์ ไร่นาที
0105569123456
02-511-3456
ผู้ติดต่อ
Contact By
ผู้สั่งชื้อสินค้า
Customer Order
PO-A-2568-01
กิตติพงษ์ วิริยะกุล
ข้าวสารหอมมะลิ 100%
500 nn. x 32.00 1/
ไข่ไก่คละเบอร์ (แผง 30 ฟอง)
200 24 x 115.00 บาท
รายการ
Description
ฝ่ายจัดซึ้ง บจก. A
งวดประจำเดือนมกราคม 2568
วันครบกำหนด าระ
เงื่อนไขในการชาระเงิน
Term of Paymers
Due Date
เงินสด
จำนวน
Quantity
ราคาต่อหน่วย
Unit Price
500
32,00
15/02/2568
จำนวนเงิน
Amount
16,000,00
200
115,00
23,000,00
1. สินค้าตามใบส่งสินค้านี้ หากมีการแตกด้าวหรือชำรุดเสียหาย กรุณาแจ้งกลับภายใน 3 วัน มิฉะนั้นทางบริษัทจะไม่รับผิดชอบใดๆ ทั้งสิ้น
2. การชำระเงินเกินกำหนดเวลาที่ตกลง จะต้องเสียดอกเบี้ยตามที่กฎหมายกำหนด
3. สินค้าตามรายการนี้ยังคงเป็นกรรมสิทธิ์ของผู้ขาย จนกว่าผู้ซื้อจะได้ชำระเงินครบถ้วนแล้ว
4. ราคานี้สำหรับค่าสั่งซื้อรอบต้นปี ยืนราคาถึงสิ้นเดือนมกราคมเท่านั้น
รวมเงิน
Total
หักเงินมัดจ่า
Depost
หักส่วนลด
Discount
รวมราคาสินค้า
ภาษีมูลค่าเพิ่ม
จำนวนเงินรวมทั้งสิ้น
Grand Teral
ได้รับสินค้าตามรายการถูกต้องเรียบร้อยแล้ว
Received the shower goods in good condition
ผู้รับสินค้า
Received by
ผู้ส่งสินค้า
Delivery by
วันที่ 31/01/2558
2.4 31/01/2558
el.
ในนาม บริษัท ฟาร์มเงินฟาร์มทอง จำกัด
For FARM NGERN FARM THONG CO. LTD
ผู้มี านาจลงนาม
Authorized Signature
39,000,00
0.00
500,00
38,500,00
2,695,00
41,195.00
"""


# Raw OCR text from the live app for the เอเชี่ยน โลจิสติกส์ invoice
# INV-6802-0147 — ground truth. All three amounts were wrong, and this one
# is entirely about damaged label text:
#   - "รวมเงินทั้งสิ้น" (the GRAND total) was claimed by the subtotal keyword
#     "รวมเงิน", which matched it first — so the total was filed as the
#     pre-tax amount and the real total went missing.
#   - OCR clipped the VAT label's first syllable: "ษีมูลค่าเพิ่ม 7%".
#   - And mangled the subtotal label "มูลค่าสินค้า/บริการ" into
#     "ทุกคาสินค้าบริการ".
REAL_ASIAN_RAW_TEXT = """บริษัท เอเชี่ยน โลจิสติกส์ ซัพพลาย จำกัด
99/12 หมู่ 4 ถนนบางนา-ตราด ตำบลบางแก้ว อำเภอบางพลี จังหวัดสมุทรปราการ
10540
เลขประจำตัวผู้เสียภาษี : 0105558012345 (สำนักงานใหญ่)
โทร. 02-345-6789 | อีเมล : accounting@asianlogisticssupply.co.th
ใบก๋ากับภาษี
TAX INVOICE
ต้นฉบับ / ORIGINAL
ลูกค้า (Customer) :
บริษัท C จำกัด
456/89 ถนนสุขุมวิท ตำบลบางเมือง อำเภอเมืองสมุทรปราการ จังหวัดสมุทรปราการ
10270
เลขประจำตัวผู้เสียภาษี : 0115569345678
เลขที่ใบกำกับภาษี
: INV-6802-0147
วันที่
เลขที่ใบสั่งซื้อ
: 18 มกราคม 2568
: PO-2568-0223
เงื่อนไขการชำระเงิน : เครดิต 30 วัน
ล่าดับ
รายการ
1 ค่าบริการขนส่งสินค้า เดือนมกราคม 2568
2
ค่าบรรจุภัณฑ์และวัสดุห่อหุ้ม
3
ค่าธรรมเนียมจัดเก็บสินค้าคลังสินค้า
จำนวนเงินรวมทั้งสิ้น (ตัวอักษร) :
หกหมื่นสามพันเก้าสิบห้าบาทถ้วน
ผู้รับสินค้า / Received by
จำนวน
หน่วย
ราคาต่อหน่วย
(บาท)
จำนวนเงิน (บาท)
1
งาน
45,000.00
45,000,00
200
อื่น
35.00
7,000.00
1
งาน
8,500.00
8,500.00
ทุกคาสินค้าบริการ
60,500.00
ษีมูลค่าเพิ่ม 7%
4,235.00
รวมเงินทั้งสิ้น
64,735.00
ผู้มีอำนาจลงนาม / Authorized signature
เอกสารนี้จัดทาขึ้นเพื่อการทดสอบระบบเท่านั้น (This document is generated for system testing purposes only)
"""


# Raw OCR text from the live app for the ไทยสยาม เทรดดิ้ง invoice
# TS-INV-016801 — ground truth. VAT and the total were wrong:
#   - "ภาษีมูลค่าเพิ่ม 7%" came through as "ภาพมูลค่าเพิ่ม 7%" (ษี misread as
#     พ), so no VAT amount was found at all.
#   - The total label "ยอดชำระสุทธิ" arrived as "ยอดชำาระสุทธิ", with SARA AM
#     doubled by a SARA AA, and matched nothing.
#   - With no total label recognised, the grand-total keyword instead
#     matched "จำนวนเงินรวมทั้งสิ้น (ตัวอักษร)" — the amount written out in
#     words, which carries no figure — and took the subtotal's 35,350.00
#     from two lines below it.
REAL_THAISIAM_RAW_TEXT = """TS
ไทยสยาม เทรดติ้ง แอนด์ ดิสทริบิวชั่น จำกัด
Thai Siam Trading & Distribution Co., Ltd.
สำนักงานใหญ่ เลขประจำตัวผู้เสียภาษี : 0107558099887
ใบกำกับภาษี
TAX INVOICE / RECEIPT
ฉบับที่ 1 : ต้นฉบับลูกค้า (CUSTOMER COPY)
ผู้ขาย / SELLER
ไทยสยาม เทรดดิ้ง แอนด์ ดิสทริบิวชั่น จำกัด
78 อาคารไทยสยามทาวเวอร์ ชั้น 12 ถนนพระราม 4
แขวงคลองเตย เขตคลองเตย กรุงเทพฯ 10110
โทร. 02-678-9900 | เลขผู้เสียภาษี : 0107558099887
ลูกค้า / CUSTOMER
บริษัท C จำกัด
456/89 ถนนสุขุมวิท ตำบลบางเมือง อำเภอเมือง
สมุทรปราการ จังหวัดสมุทรปราการ 10270
เลขประจำตัวผู้เสียภาษี : 0115569345678
รายละเอียดเอกสาร
เลขที่เอกสาร
วันที่ออก
อ้างอิงใบสั่งซื้อ
สกุลเงิน
TS-INV-016801
22 มกราคม 2568
PO-6801-088
THB
รายละเอียดสินค้า/บริการ
1 อุปกรณ์สำนักงาน รุ่นมาตรฐาน (ชุดคละแบบ)
2
ค่าติดตั้งและฝึกอบรมการใช้งานระบบ
จำนวน
หน่วย
ราคา/หน่วย
ส่วนลด
จำนวนเงิน
15
ชุด
1,290.00
0.00
19,350.00
1
งาน
12,000.00
1,000.00
11,000.00
3 ค่าบริการบำรุงรักษารายเดือน (มกราคม 2568)
1
เดือน
3,500.00
0.00
3,500.00
4
ค่าจัดส่งและขนถ่ายสินค้า
1
งาน
1,500.00
0.00
1,500.00
จำนวนเงินรวมทั้งสิ้น (ตัวอักษร)
รวมมูลค่าสินค้า/บริการ
35,350,00
สามหมื่นหกพันเจ็ดร้อยห้าสิบสี่บาทห้าสิบสตางค์
ส่วนลดรวม
-1,000.00
เงื่อนไขการชำระเงิน: โอนเข้าบัญชีภายใน 30 วันนับจากวันที่ในใบกำกับ
ภาษี
มูลค่าหลังหักส่วนลด
34,350.00
สแกนเพื่อตรวจสอบ e-Tax Invoice
ภาพมูลค่าเพิ่ม 7%
2,404.50
ยอดชำาระสุทธิ
36,754.50
ผู้จัดทำเอกสาร
ผู้ตรวจสอบ
ผู้มีอำนาจอนุมัติ
เอกสารนี้จัดทำขึ้นเพื่อการทดสอบระบบเท่านั้น (Generated for OCR/system testing purposes only) - ไม่ใช่เอกสารทางการเงินจริง
"""


# Raw OCR text from the live app for the อรุณเทสต์ sample invoice INV-0001.
# Four fields were wrong, three of them from ONE cause: the taxpayer ID on
# this document is twelve digits (990000010014), and requiring exactly
# thirteen meant no ID was found at all — so a full tax invoice was
# classified ใบย่อ and ม.86/6 wiped the subtotal and VAT it plainly shows.
# Separately, the buyer is literally named "ลูกค้าตัวอย่าง", and the rule
# that skips lines containing "ลูกค้า" (meant for labels) discarded it,
# leaving the seller's logo line "ARUN TEST สาขา สำนักงานใหญ่" to win.
REAL_ARUN_RAW_TEXT = """บริษัท อรุณเทสต์ โซลูชัน จำกัต
ARUN TEST SOLUTIONS CO., LTD.
เลขประจำตัวผู้เสียภาษีอากร 990000010014
ARUN TEST สาขา สำนักงานใหญ่
SOLUTIONS
123 ถนนตัวอย่าง ตำบลตัวอย่าง จังหวัดตัวอย่าง 50000
ใบกำกับภาษี
TAX INVOICE
เลขที่ใบกำกับภาษี
(Invoice No.)
: INV-0001
วันที่ออกใบกำกับภาษี : 08/03/2026
(Invoice Date)
ลูกค้า / Customer
ชื่อลูกค้า
:
ที่อยู่
ลูกค้าตัวอย่าง
: 123 ถนนตัวอย่าง ตำบลตัวอย่าง
จังหวัดตัวอย่าง 50000
ล่าดับ
No.
รายการ
Description
จำนวน
Quantity
หน่วย
1
สินค้าตัวอย่าง A
5
2
สินค้าตัวอย่าง B
Unit Price
2,500.00
จำนวนเงิน
Amount (THB)
SAMPLE-TEST ONLY AND FOR TAX
3 ค่าบริการตัวอย่าง
12,500.00
ชิ้น
3,750.00
11,250.00
1
รายการ
1,000.50
1,000.50
หมายเหตุ / Remarks
เอกสารนี้เป็นข้อมูลสมมติสำหรับทดสอบระบบเท่านั้น
มูลค่าสินค้า/บริการ (Subtotal)
24,750.50
ภาษีมูลค่าเพิ่ม 7% (VAT 7%)
1,732.54
This document is a sample for testing purposes only.
จำนวนเงินรวมทั้งสิ้น (Total)
26,483.04
วันที่
ผู้จัดทำ
(Prepared by)
SAMPLE - TEST ONLY - NOT VALID FOR TAX
วันที่
ผู้มีอำนาจลงนาม
(Authorized Signature)
"""


# Raw OCR text from the live app for the บลูไพน์ ดิจิทัล sample invoice
# INV-0002. This one labels its buyer "ข้อมูลผู้ซื้อ / BUYER" — a wording
# the keyword list didn't know (it had นามผู้ซื้อ / ชื่อผู้ซื้อ / ลูกค้า /
# Customer / Bill To). With no buyer found, the same cascade as always: not
# a full tax invoice, so ม.86/6 wiped the subtotal and VAT it prints.
REAL_BLUEPINE_RAW_TEXT = """BP
บริษัท บลูไพน์ ดิจิทัล จำกัด
ใบกำกับภาษี / TAX INVOICE
Test ID: TEST-002
SAMPLE – TEST ONLY – NOT VALID FOR TAX
ข้อมูลผู้ขาย / SELLER
บริษัท บลูไพน์ ดิจิทัล จำกัด
เลขประจำตัวผู้เสียภาษี / Tax ID: 990000010023
สาขา / Branch: สำนักงานใหญ่
เลขที่ใบกำกับภาษี / Invoice No.
INV-0002
วันที่ / Invoice Date
14/05/2026
ข้อมูลผู้ซื้อ / BUYER
บริษัท ตัวอย่าง เทคโนโลยี จำกัด
123 ถนนตัวอย่าง ตำบลตัวอย่าง อำเภอตัวอย่าง จังหวัดตัวอย่าง 50000
ลำดับ
 No.
รายการ
Description
จำนวน
 Qty
ราคาต่อหน่วย
 Unit Price
จำนวนเงิน
 Amount
1
จอภาพคอมพิวเตอร์ 24 นิ้ว
2
4,500.00
9,000.00
2
คีย์บอร์ดไร้สาย
3
850.00
2,550.00
3
อุปกรณ์ขยายพอร์ต USB-C
1
1,440.25
1,440.25
ยอดก่อนภาษี / Subtotal
12,990.25
ภาษีมูลค่าเพิ่ม 7% / VAT 7%
909.32
ยอดรวม / Total
13,899.57
Template: T01
TEST-002
SAMPLE – TEST ONLY – NOT VALID FOR TAX
"""


# Raw OCR text from the live app for the พรเจริญ เทคโนโลยี invoice
# INV-6808-015. Two fields were wrong, both because OCR shuffled unrelated
# blocks into the middle of others:
#   - The buyer's ADDRESS ("55/99 หมู่ 6 ถนนมหิดล...") landed between the
#     "เลขที่ / NO." label and its value, so "55/99" was filed as the
#     invoice number.
#   - The seller's tagline ("จำหน่ายอุปกรณ์ไอที / อุปกรณ์สำนักงาน / และ
#     โซลูชั่น...") landed below the buyer label. "อุปกรณ์สำนักงาน" counted
#     as an entity name because of "สำนักงาน", and beat the real buyer four
#     lines ABOVE the label, since any line below used to outrank any line
#     above no matter the distance.
REAL_PORNJAROEN_RAW_TEXT = """ว
PORNJAROEN
TECHNOLOGY
บริษัท พรเจริญ เทคโนโลยี จำกัด (สำนักงานใหญ่)
PORNJAROEN TECHNOLOGY CO., LTD. (Head Office)
128/56 ถนนเชียงใหม่-ลำพูน ตำบลหนองหอย อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50000
โทร. 053-248-789 อีเมล: info@pornjaroentech.co.th เว็บไซต์: www.pornjaroentech.co.th
เลขประจำตัวผู้เสียภาษีอากร / Tax ID
9900000200421
นามผู้ฌอ / Name
บริษัท เชียงใหม่ ดีไซน์ จำกัด
ที่อยู่ / Address
ใบเสร็จรับเงิน / ใบกำกับภาษี
RECEIPT / TAX INVOICE
ต้นฉบับสำหรับลูกค้า / Original
เลขที่ / NO.
วันที่ / DATE
55/99 หมู่ 6 ถนนมหิดล ตำบลสุเทพ อำเภอเมืองเชียงใหม่
จังหวัดเชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษีอากร / Tax ID
0505567001234
เครดิต / CREDIT
วันครบกำหนด / DUE DATE
เลขที่ใบสั่งซื้อ / PO.NO
พนักงานขาย / SALEMAN
รหัสลูกค้า / CUSTOMER
จำหน่ายอุปกรณ์ไอที
อุปกรณ์สำนักงาน
และโชลูชั่นด้านเทคโนโลยี
INV-6808-015
18/08/2568
30 วัน
17/09/2568
PO-6808-0312
น.ส. กฤตยา ใจดี
CUST-0152
สินค้าก่อนหักส่วนลด
129,750.00
หัก ส่วนลดรวม
2,250.00
มูลค่าสินค้าหลังหักส่วนลด
ภาษีมูลค่าเพิ่ม (VAT 7%)
หัก เงินมัดจำ
รวมมูลค่าทั้งสิ้น
127,500.00
8,925.00
0.00
136,425.00
"""

# The กรีนฟิลด์ invoice from the live app. Google Vision read the CUSTOMER
# box before the letterhead, so the page opens "ลูกค้า / Customer" /
# "บริษัท สตาร์เทรดดิ้ง จำกัด" / "บริษัท กรีนฟิลด์ ออฟฟิศ ซัพพลาย จำกัด" —
# the buyer's name printed above the seller's. Taking the first
# company-looking line as the seller put the two names in each other's
# boxes: the buyer was filed as the issuer and the issuer as the buyer.
# The page also carries three dates, and the credit-30-days due date
# ("วันที่ครบกำหนดชำระ : 15/10/2026") was read out ahead of the issue date
# ("วันที่ออกใบกำกับภาษี / 15/09/2026"), so the invoice was filed a month
# late, under its own payment deadline.
REAL_GREENFIELD_RAW_TEXT = """GREENFIELD
OFFICE SUPPLY
ลูกค้า / Customer
บริษัท สตาร์เทรดดิ้ง จำกัด
บริษัท กรีนฟิลด์ ออฟฟิศ ซัพพลาย จำกัด
Greenfield Office Supply Co., Ltd.
88/9 ถนนสุขวิต ตำบลบางจาก อำเภอพระโขนง จังหวัดกรุงเทพมหานคร 10260
เลขประจำตัวผู้เสียภาษี : 0105567012348 (สำนักงานใหญ่)
โทร. 02-779-8899 | อีเมล : sales@greenfield.co.th
99/1 ถนนตัวอย่าง แขวงดินแดง เขตดินแดง
กรุงเทพมหานคร 10400
เลขประจำตัวผู้เสียภาษี : 0123456789012
เลขที่ใบสั่งซื้อ (PO No.)
: PO-2026-0775
เงื่อนไขการชำระเงิน
วันที่ครบกำหนดชำระ
: เครดิต 30 วัน
: 15/10/2026
พนักงานขาย
: คุณณัฐชา
ใบกำกับภาษี
TAX INVOICE
ต้นฉบับ / ORIGINAL
เอกสารเลขที่
GF-INV-2026-0098
วันที่ออกใบกำกับภาษี
15/09/2026
ลำดับ
No.
รายการสินค้า / บริการ
Description
จำนวน
หน่วย
Quantity
Unit
ราคาต่อหน่วย
(บาท)
Unit Price (Baht)
จำนวนเงิน
(บาท)
Amount (Baht)
1
กระดาษถ่ายเอกสาร A4 (500 แผ่น)
10
10
รีม
135.00
1,350.00
2
ปากกาลูกลื่น (สีน้ำเงิน)
550
ด้าม
12.00
600.00
3
แฟ้มเอกสารสันกว้าง
20
เล่ม
55.00
1,100.00
4
สมุดโน้ต A5
30
เล่ม
25.00
750.00
5
กล่องเก็บเอกสาร
10
กล่อง
120.00
1,200.00
หมายเหตุ / Remark
1. สินค้ารวมภาษีมูลค่าเพิ่มแล้ว
2. กรุณาตรวจสอบรายการสินค้า/บริการและจำนวนเงินให้ถูกต้อง
3. หากมีข้อสงสัยกรุณาติดต่อฝ่ายขาย
B
ผู้มีอำนาจลงนาม
(Authorized Signature)
นางสาวกมลวรรณ ใจดี
กรรมการผู้จัดการ
มูลค่าสินค้า/บริการ (Subtotal)
5,000.00
ภาษีมูลค่าเพิ่ม 7% (VAT 7%)
รวมเงินทั้งสิ้น (Total)
350.00
5,350.00
(ห้าพันสามร้อยห้าสิบบาทถ้วน)
ขอขอบคุณที่ใช้บริการ
Thank you for your business
SAMPLE - TEST ONLY - NOT VALID FOR TAX
เอกสารนี้จัดทำขึ้นเพื่อการทดสอบระบบเท่านั้น
(This document is generated for system testing purposes only)
"""

# The บลูมูน invoice from the live app. Two separate defects.
# (1) The letterhead prints the logo wordmark "BLUEMOON" / "TRADING CO.,
#     LTD." above the registered name, and that second line was taken for
#     the company — the seller was filed as "TRADING CO., LTD.". The
#     registered name itself came out broken in two AND in reverse order,
#     "เทรดดิ้ง จำกัด" before "บริษัท บลูมูน", so even finding the right line
#     yielded only half a name.
# (2) The seller's taxpayer ID is letter-spaced across its box
#     ("0 5 0 5512345678") and matched no plain 13-digit run, so the first
#     13 digits found on the page were the CUSTOMER's 0994000123456 —
#     filed as the issuer's ID.
REAL_BLUEMOON_RAW_TEXT = """BLUEMOON
TRADING CO., LTD.
GOOD PRODUCTS BETTER EVERYDAY
เทรดดิ้ง จำกัด
บริษัท บลูมูน
BLUEMOON TRADING CO., LTD.
789/12 หมู่ 5 ถนนซุปเปอร์ไฮเวย์ ตำบลฟ้าฮ่าม
อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50000
โทร. 052-010-789 แฟกซ์ 052-010-790
อีเมล: info@bluemoontrading.co.th
เว็บไซต์: www.bluemoontrading.co.th
เลขประจำตัวผู้เสียภาษีอากร 0 5 0 5512345678
(สำนักงานใหญ่)
ใบกำกับภาษีเต็มรูป
TAX INVOICE
TRUST
QUALITY
PARTNERSHIP
FOR A BRIGHTER
TOMORROW
"เคียงข้างธุรกิจคุณ
ในทุกเส้นทาง"
ข้อมูลใบกำกับภาษี (Invoice Information)
ต้นฉบับ
(Original)
ข้อมูลลูกค้า (Customer)
ชื่อผู้ซื้อ : บริษัท เชียงใหม่กูร์เม่ต์ จำกัด
เลขประจำตัวผู้เสียภาษีอากร :
0994000123456
ที่อยู่ : 321 หมู่ 8 ถนนเชียงใหม่-ลำพูน
ตำบลหนองหอย อำเภอเมืองเชียงใหม่
เลขที่ใบกำกับภาษี
: BM-2026081507
จังหวัดเชียงใหม่ 50000
โทรศัพท์
: 053-333-222
วันที่ออกใบกำกับภาษี : 15 สิงหาคม 2568
วันที่ครบกำหนดชำระ : 29 สิงหาคม 2568
เงื่อนไขการชำระเงิน : ชำระภายใน 14 วัน
พนักงานขาย
อ้างอิงใบสั่งซื้อ
: นางสาวกมลชนก ใจดี
: PO-CMG680815
อีเมล
: procurement@cmgourmet.co.th
อ้างอิงใบเสนอราคา
: QT-680810
ล่าดับ
No.
รายการสินค้า / บริการ
Description
จำนวน
หน่วย
ราคาต่อหน่วย
Quantity
Unit
(บาท)
Unit Price (THB)
จำนวนเงิน
(บาท)
Amount (THB)
1
เมล็ดกาแฟคั่วพิเศษ (Arabica) ขนาด 1 กก.
50
ถุง
480.00
24,000.00
2
ชาเขียวมัทฉะ เกรดพรีเมียม ขนาด 500 กรัม
30
ถุง
620.00
18,600.00
3
น้ำเชื่อมกลิ่นวานิลลา ขนาด 750 มล.
40
ขวด
85.00
3,400.00
4
แก้วกระดาษ รุ่น Eco Cup 16 oz (แพ็ก 50 ใบ)
100
แพ็ก
120.00
12,000.00
5
ค่าจัดส่งสินค้า
1
เที่ยว
1,000.00
1,000.00
หมายเหตุ
รวมจำนวนเงิน (ก่อนภาษีมูลค่าเพิ่ม)
59,000.00
ภาษีมูลค่าเพิ่ม 7%
รวมจำนวนเงินทั้งสิ้น
4,130.00
63,130.00
1. ราคานี้รวมค่าจัดส่งภายในจังหวัดเชียงใหม่
2. สินค้ารับประกันคุณภาพตามเงื่อนไขของบริษัทฯ
3. หากมีข้อสงสัยกรุณาติดต่อฝ่ายบริการลูกค้า โทร. 052-010-789
4. เอกสารนี้เป็นใบกำกับภาษีเต็มรูปตามประมวลรัษฎากร
ผู้จัดทำ / ออกใบกำกับภาษี
In
( นางสาวศิรินทร์ วัฒนกุล )
เจ้าหน้าที่บัญชี
วันที่ 15 สิงหาคม 2568
ผู้มีอานาจลงนาม
n
( นายอภิวัฒน์ รัตนกุล )
กรรมการผู้จัดการ
วันที่ 15 สิงหาคม 2568
(หกหมื่นสามพันหนึ่งร้อยสามสิบบาทถ้วน)
สแกนเพื่อตรวจสอบ
ข้อมูลใบกำกับภาษี
ผ่านระบบ e-Tax Invoice
ของกรมสรรพากร
052-010-789 M info@bluemoontrading.co.th
9 www.bluemoontrading.co.th
SUSTAINABLE BUSINESS
FOR A BRIGHTER TOMORROW
"""

# The กรีนฟิลด์ ซัพพลาย invoice from the live app. The page labels two
# taxpayer IDs, and OCR damaged exactly one of them: the seller's label
# came out "เลขประจำตัวผู้เสียกษีอากร" — the ภา of ภาษี dropped — while the
# customer's "เลขประจำตัวผู้เสียภาษีอากร :" survived intact. The only label
# that matched was therefore the buyer's, and the invoice was filed under
# the customer's ID. Both IDs are also letter-spaced across their boxes
# ("0 5 0 5 5 1 2 3 4 5 6 7 8").
REAL_GREENFIELD_SUPPLY_RAW_TEXT = """บริษัท กรีนฟิลด์ ซัพพลาย จำกัด
GREENFIELD SUPPLY CO., LTD.
456 หมู่ 7 ถนนซูปเปอร์ไฮเวย์ ตำบลหนองควาย
อ้าเภอหางดง จังหวัดเชียงใหม่ 50230
โทร. 053-888-123 แฟกซ์ 053-888-124
GREENFIELD อีเมล: sales@greenfieldsupply.co.th
SUPPLY CO., LTD.
CLEAN ENERGY FOR A BETTER TOMORROW
เว็บไชต์: www.greenfieldsupply.co.th
เลขประจำตัวผู้เสียกษีอากร 0 5 0 5 5 1 2 3 4 5 6 7 8
(สำนักงาบใหญ)
ใบกำกับภาษีเต็มรูป
TAX INVOICE
SUSTAINABLE
PRODUCTS
SUSTAINABLE
LIVING
"ร่วมสร้าง
สิ่งแวดล้อมที่ดีกว่า
ให้กับอนาคต"
ต้นฉบับ
(Original)
ข้อมูลลูกค้า (Customer)
ชื่อผู้ซื้อ : บริษัท เชียงใหม่ เบเกอรี่ แอนด์ คาเฟ่ จำกัด
เลขประจำตัวผู้เสียภาษีอากร : 050554 7 8 9 0 1 2 3
ที่อยู่
: 99 หมู่ 1 ถนนนิมมานเหมินทร์ ตำบลสุเทพ
อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50200
โทรศัพท์ : 053-242-567
ข้อมูลใบกำกับภาษี (Invoice Information)
เลขที่ใบกำกับภาษี : GF-2026081501
วันที่ออกใบกำกับภาษี : 15 สิงหาคม 2568
วันที่ครบกำหนดชำระ : 29 สิงหาคม 2568
เงื่อนไขการชำระเงิน - ชำระภายใน 14 วัน
: นางสาวกมลวรรณ ใจดี
อีเมล
: accounting@cmbakery.co.th
พนักงานขาย
อ้างอิงใบสั่งซื้อ
อ้างอิงใบเสนอราคา
: PO-CMB250815
: QU-20250810
ล่าดับ
No.
รายการสินค้า / บริการ
Description
จำนวน
หน่วย
Quantity
Unit
ราคาต่อหน่วย
(บาท)
Unit Price (THB)
จำนวนเงิน
(บาท)
Amount (THB)
1
เมล็ดกาแฟอาราบิก้า คั่วกลาง (1 กก.)
20
2
ถุงบรรจุภัณฑ์ ขีปล็อก ขนาด 250 กรัม
500
3 กล่องกระดาษรักษ์โลก ขนาด M
200
22 2
ถุง
950.00
19,000.00
ใบ
6.50
3,250.00
12.00
2,400.00
4 สติ๊กเกอร์โลโก้ (พิมพ์ 4 สี)
1,000
ดวง
1.20
1,200.00
5 ค่าจัดส่งสินค้า
1
เที่ยว
1,500.00
1,500.00
หมายเหตุ
1. ราคานี้รวมค่าจัดส่งภายในจังหวัดเชียงใหม่
2. สินค้ารับประกันคุณภาพตามเงื่อนไขของบริษัทฯ
3. หากมีข้อสงสัยกรุณาติดต่อฝ่าขยาย โทร. 053-888-123
4. เอกสารนี้เป็นใบกำกับภาษีเต็มรูปตามประมวลรัษฎากร
KE
ข้อมูลการชำระเงิน (Bank Information)
ธนาคารกสิกรไทย จำกัด (มหาชน)
สาขาเชียงใหม่
ชื่อบัญชี บริษัท กรีนฟิลด์ ซัพพลาย จำกัด
เลขที่บัญชี 123-8-45678-9
ประเภทบัญชี กระแสรายวัน
(สองหมื่นเก้าพันสองร้อยหกสิบสี่บาทห้าสิบสตางค์)
ผู้จัดทำ / ออกใบกำกับภาษี
(ph
( นางสาวศิริพร มานะกุล)
เจ้าหน้าที่บัญชี
วันที่ 15 สิงหาคม 2568
ผู้มีอำนาจลงนาม
Ime
(นายธนวัฒน์ ประเสริฐกุล )
กรรมการผู้จัดการ
วันที่ 15 สิงหาคม 2568
รวมจำนวนเงิน (ก่อนภาษีมูลค่าเพิ่ม)
27,350.00
ภาษีมูลค่าเพิ่ม 7%
รวมจำนวนเงินทั้งสิ้น
1,914.50
29,264.50
053-888-123 X sales@greenfieldsupply.co.th
GOOD PRODUCTS
www.greenfieldsupply.co.th
BRIGHTER TOMORROW
สแกนเพื่อตรวจสอบ
ใบก๋ากับภาษี
"""

# The โคราชเทค invoice from the live app. Its totals box has six rows, and
# OCR emitted them in three pieces: five labels ("หัก ส่วนลดรวม" ...
# "รวมมูลค่าทั้งสิ้น"), then the last row of the ITEMS table dropped in the
# middle ("V", "5", "กล่อง", "90.00", "0.00", "450.00"), then the sixth
# label ("สินค้าก่อนหักส่วนลด"), then all six figures together. No label run
# ever reached its own values — the run of five ran straight into the item
# row's "5" and paired against it — so all three amounts fell through to a
# keyword search, which returned an item line number (1), the seller's
# postcode (30,000) and another line number (5).
REAL_KORATTECH_RAW_TEXT = """T
บริษัท โคราชเทค อินโนเวชั่น จำกัด (สำนักงานใหญ่)
KORATTECH INNOVATION CO., LTD. (Head Office)
129/45 ถนนราชสีมา-ปีกธงชัย ตำบลหนองจะบก อำเภอเมืองนครราชสีมา จังหวัดนครราชสีมา 30000
129/45 Ratchasima-Pak Thong Chai Road, Nong Chabok Subdistrict,
KoratTech Mueang Nakhon Ratchasima District, Nakhon Ratchasima 30000
Innovation Co., Ltd.
OFFICE FURNITURE SOLUTIONS
FOR A BETTER WORKSPACE
เลขประจำตัวผู้เสียภาษีอากร / Tax ID
0105569018274
นามผู้ซื้อ / Name
บริษัท เอสพี เคมิคอล จำกัด
ที่อยู่ / Address
Ins. 044-xxx-xxxx
Email: info@korattech.co.th
เลขประจำตัวผู้เสียภาษีอากร 0105569018274
88/9 หมู่ที่ 4 ถนนมิตรภาพ ตำบลในเมือง
อ๋าเภอเมืองขอนแก่น จังหวัดขอนแก่น 40000
เลขประจำตัวผู้เสียภาษีอากร / Tax ID
0405567001234
รายการ
Website: www.korattech.co.th
ใบเสร็จรับเงิน / ใบกำกับภาษี
RECEIPT / TAX INVOICE
ต้นฉบับสำหรับลูกค้า / Original
เลขที่ / NO.
วันที่ / DATE
เครดิต / CREDIT
INV-6809045
09/09/2568
30 วัน
วันครบกำหนด / DUE DATE 09/10/2568
เลขที่ใบสั่งซื้อ / PO.NO
พนักงานขาย / SALEMAN
รหัสลูกค้า / CUSTOMER
ราคาต่อหน่วย
เฟอร์นิเจอร์สำนักงาน
ที่ตอบโจทย์ทุกพื้นที่ทำงาน
"Smart Workspace
PO-20250901
Better Tomorrow "
นายธนกฤต ศรีวัฒนา
CUS-0123
หน้าที่ 1/1
ลำดับที่
จำนวน
หน่วยนับ
ส่วนลดต่อหน่วย
V/N*
ITEM
DESCRIPTION
QUANTITY
UNIT
UNIT PRICE
DISCOUNT
จำนวนเงินบาท
AMOUNT (BAHT)
1
โต๊ะทำงาน ขนาด 120 cm.
V
2
ตัว
2,800.00
0.00
5,600.00
(Office Desk)
2
เก้าอี้สำนักงาน รุ่น Ergo
V
4
ตัว
980.00
50.00
3,720.00
(Office Chair)
3
ตู้เอกสาร 2 บานเปิด
V
1
2,500.00
0.00
2,500.00
(Storage Cabinet)
4
ชั้นวางแฟ้ม 3 ชั้น
V
1
ตัว
650.00
0.00
650.00
(File Shelf)
5
กล่องเก็บเอกสารพลาสติก
(Document Box)
หมายเหตุ * (V = สินค้าทำบารมีอมูลสินค้า /
N = สินค้าไม่กำหนดแต้มส่งเสริมการขาย)
1. สินค้ารับประกัน 1 ปี (ยกเว้นสินค้าที่สึกหรือง)
2. ราคาที่รวมภาษีมูลค่าเพิ่ม
หัก ส่วนลดรวม
มูลค่าสินค้าหลังหักส่วนลด
ภาษีมูลค่าเพิ่ม (VAT 7%)
หัก เงินมัดจำ
รวมมูลค่าทั้งสิ้น
V
5
กล่อง
90.00
0.00
450.00
สินค้าก่อนหักส่วนลด
12,430.00
200.00
12,230.00
856.10
0.00
13,086.10
จำนวนเงินรวม (ตัวอักษร)
GRAND TOTAL (ALPHABET)
หนึ่งหมื่นสามพันแปดสิบหกบาทสิบสตางค์
- สินค้าบริการในใบกำกับภาษีนี้ ได้รับชำระเงินและส่งมอบเรียบร้อยแล้ว
- โปรดตรวจสอบรายการสินค้า หากมีข้อผิดพลาดกรุณาแจ้งภายใน 7 วัน
- บริษัทฯ ขอสงวนสิทธิ์ในการเปลี่ยนคืนสินค้าเฉพาะกรณีสินค้ามีตำหนิจากการผลิต
- ใบกำกับภาษีนี้เป็นหลักฐานทางภาษี โปรดเก็บรักษาไว้
- ขอบคุณที่ไว้วางใจใช้บริการ
บริษัท โคราชเทค อินโนเวชั่น จำกัด
Muk
(นางสาวกมลชนก วิริยะกุล)
ผู้มีอำนาจลงนาม
AUTHORIZED SIGNATURE
"""

# The ขอนแก่น โปรออฟฟิศ invoice from the live app — a badly degraded scan
# that broke four fields at once, each a different way.
# (1) The letterhead wrapped its branch marker onto the next line, so the
#     seller came out "บริษัท ... จำกัด (สานักงาน" with "ใหญ่)" stranded below.
# (2) The copy designation "ต้นฉบับสำหรับลูกค้า / Original" was read as
#     "นพัน ลูกค้า/Original" — enough of "ลูกค้า" survived to make the line
#     above the SELLER's taxpayer ID look like a customer box, so that ID
#     was skipped and the buyer's was filed as the issuer's.
# (3) The document box prints its values behind a colon (": INV-6809-042"),
#     which no value pattern matched, so the scan ran on to the items
#     table and filed the invoice under the number "ITEM".
# (4) The buyer label "นามผู้ซื้อ / Name :" came out "นามสื่อ / Name :" and
#     matched nothing, so the whole line went into the ชื่อผู้ซื้อ box.
REAL_KHONKAEN_RAW_TEXT = """KPO
SUPPLY
บริษัท ขอนแก่น โปรออฟฟิศ ซัพพลาย จำกัด (สานักงาน
ใหญ่)
KHONKAEN PROOFFICE SUPPLY CO., LTD. (Head Office)
128/36 อนแ ลบภาพ ท่าน ในวิอร อ่าเกรเêereeukrit en esอนแก่น 40000
128/36 Mittraphap Road, Nai Mueang, Mueang Khon Kaen, Khon Khen 40000
โทร. 023-221-569 Email: contact@kkprooffice.co.th Website: www.kkprooffice.co.th
ใบเสร็จรับเงิน/ใบก่ากับภาษี
RECEIPT / TAX INVOICE
นพัน ลูกค้า/Original
เลขประจำตัวผู้เสียภาษีอากร / Tax ID : 0105568123476
นามสื่อ / Name : บริษัท อิสาน พัฒนาการค้า จำกัด (สำนักงานใหญ่)
ที่อยู่ / Address : 88/12 นิตรภาพ ตำบลศิลา อำเภอเมืองขอนแก่น จังหวัดขอนแก่น
40000
เลขประจำตัวผู้เสียภาษีอากร / Tax ID : 0405561009871
ดุน งามเห่อเอานักงาน
uarq กรณ์ทำความสะอาดหงบ
325
Quality Office Furniture &
Cleaning Supplies Solutions
หน้า 1/1
เลขที่ / NO.
: INV-6809-042
วันที / DATE
เครติด / CREDIT
: 18/09/2568
: 30 วัน
ล่าสันหี
ITEM
รายการ
DESCRIPTION
1 หาอีสานักรานหนักหินสูง Ergonomic (รุ่น Pro-Desk)
2
3
4
โต๊ะทำงานอเนกประสงค์ 120 ซม. (ลายไม้แอช)
น้ำยาถูพื้นทำความสะอาดขจัดคราบ Heavy Duty 5 ลิตร
ชุดไม้ถูพื้นไมโครไฟเบอร์พร้อมถังปั่นสแตนเลส
หมายเหตุ * (V = สินค้าผ่านภาษีมูลค่าเพิ่ม / N = สินค้าไม่คิดภาษีมูลค่าเพิ่ม)
1. สินค้ารับประทับสุภาพ 1 ปี (ยกเว้นอุปกรณ์สนเปลือง)
2. ราคารวมภาษีมูลค่าเห็นเรียบร้อยแล้ว
3. กรุณาอวสอบราชการสินค้า และจำนวนห้า หกต้อง
วันครบก้าหนด / DUE
: 18/10/2568
DATE
เลข ในลอสื่อ / PO.NO : PO-2025-089
พนักงานขาย/
SALESMAN
รหัสลูกค้า/
CUSTOMER
:นายสมชาย ใx
:CUS-KK-0142
V/N°
จำนวน
QUANTITY
หน่วงนับราคาส่งหน่วย
จำนวนเงินบาท
UNIT
UNIT PRICE
AMOUNT (BAHT)
< < < <
V
2
ตัว
2,850.00
5,700.00
V
ตัว
2,200.00
2,200.00
V
2
แกลลอน
380.00
760.00
V
ชุด
690.00
690.00
รวมหิน / Subtotal
หัก ส่วนออทิเce / Discount
จำนวนเงินหลังหักส่วนลด
กาอิมูลค่าเพิ่ม / VAT 7%
หัก พินมัดจำ / Deposit
เก้าพันสามร้อยฟังลั่น / Grand Total
9,350.00
612.15
8,737.55
611.65
0.00
9,349.50
.
จำนวนเงินราม (ผ้าอักษร) :
- สินค้าตามบริการใบกำกับภาษีนี้ ได้รับชำระเงินและส่งมอบเรียบร้อยแล้ว
- โบ่รอดราวสอบราชการลินค้า หากมีข้อผิดหลายกรุณาะลังกา ใน 7 วัน
- บอย ซอสงวนสิทธิ์ในการเปลื่อน /ดินดินผ้าลายเรือน สินค้าที่ทำหนด
ใบกำกับการ เป็นหลักฐานลายภาษี โปรเก็บรักษาไว้
ชอบอุณห า ส บ การ
เก้าพันสามร้อยสี่สิบเค้าบาทห้าสิบสตางค์
บริษัท ขอนแก่น โย่vaอหหิต พพลาย จำกัด
(นางสาว คายา กระ ยากุล)
อ่านโนลงนาม
AUTHORIZED SIONATURE
"""

# The บลูมมิ่ง ไลฟ์ invoice from the live app. It labels NEITHER party —
# the seller's address block sits at the top, the customer's below it, and
# no "ชื่อผู้ซื้อ" or "ลูกค้า" appears anywhere on the page. Every buyer
# search is keyed on such a label, so the buyer came back empty, and one
# missing name cost three more fields: no buyer means the document is
# classified ย่อ, and ม.86/6 then wipes the subtotal and the VAT it plainly
# printed. The user reported all four as separate errors; they are one.
REAL_BLOOMING_RAW_TEXT = """บริษัท บลูมมิ่ง ไลฟ์ จำกัด
120 ถนนเชียงใหม่-ลำพูน ตำบลหนองหอย อำเภอเมือง
เชียงใหม่ จังหวัดเชียงใหม่ 50000
เลขประจำตัวผู้เสียภาษี 0134563248907
โทร 08756334210
ใบกำกับภาษี
TAX INVOICE
เลขที่
Inv001-57
วันที่
07/01/2025
พนักงานขาย
อโดรา มอนต์มินี
บริษัท B จำกัด
188 หมู่ 7 ถนนเชียงใหม่-ลำพูน ตำบลหนองผึ้ง อำเภอสารภี
จังหวัดเชียงใหม่ 50140
เลขประจำตัวผู้เสียภาษี 0505569234567
ครบกำหนดชำระ 07/01/2025
หมายเลขอ้างอิง 01057
ล่าดับ
1
เครื่องคิดเลข
2
กระดาษทิชชู่
3
แก้วกระดาษ
รายการ
จำนวน
หน่วยละ
จำนวนเงิน
2
230.00
460.00
4
80.00
320.00
3
55.00
165.00
รวมทั้งสิ้น
(เก้าร้อยสี่สิบห้าบาทถ้วน)
ภาษีมูลค่าเพิ่ม 7%
จำนวนเงินสุทธิ
883.18 บาท
61.82 บาท
945.00 บาท
ช่องทางการชำระเงิน:
ชื่อบัญชี บริษัท บลูมมิ่ง ไลฟ์ จำกัด
เลขที่บัญชี 0123 45678901
ธนาคาร ABC
D
ผู้รับเงิน
07/01/2025
วันที่
"""

# The บลูมแอนด์โค invoice from the live app. Its header box was read column
# by column, values before labels, so the page runs "INV-2026-091" /
# "ลูกค้า / Customer" / "เลขที่ใบกำกับภาษี" — the number two lines ABOVE the
# label that names it. The forward search therefore ran past the label,
# into the customer box, and filed the invoice under "789", the house
# number of the buyer's address. The customer box then labels its value
# "ชื่อบริษัท", which carries no buyer keyword at all, so that label itself
# was recorded as the buyer's name and the name on the next line was
# never reached.
REAL_BLOOMANDCO_RAW_TEXT = """"สิ่งเล็ก ๆ
สร้างความสุขได้เสมอ"
GOOD THINGS
FOR A BRIGHTER DAY
ใบกำกับภาษี
TAX
INVOICE
ต้นฉบับ / ORIGINAL
BLOOM&CO.
LIFESTYLE FOR A BETTER YOU
บริษัท บลูมแอนด์โค ไลฟ์สไตล์ จำกัด
เลขประจำตัวผู้เสียภาษีอากร 0105567004321
321/45 ถนนนิมมานเหมินทร์ ตำบลสุเทพ
อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50200
โทร. 053-214-789 อีเมล: info@bloomandco.co.th
เว็บไซต์: www.bloomandco.co.th
INV-2026-091
ลูกค้า / Customer
เลขที่ใบกำกับภาษี
ชื่อบริษัท
บริษัท เวลเนส พลัส จำกัด
ที่อยู่
789 หมู่ 3 ถนนวงแหวนรอบสอง
ตำบลสันผีเสื้อ อำเภอเมืองเชียงใหม่
วันที่ออกใบกำกับภาษี
05/09/2569
วันครบกำหนดชาระเงิน
05/10/2569
เงื่อนไขการชาระเงิน
30 วัน
จังหวัดเชียงใหม่ 50300
เลขประจำตัวผู้เสียภาษีอากร 0505567004321
พนักงานขาย
น.ส. ปรียาภรณ์ ใจดี
0
รหัสลูกค้า
WL-0036
ลำดับ
No.
รายการสินค้า / รายละเอียด
Description
จำนวน หน่วย
ราคาต่อหน่วย
ส่วนลด
Quantity
Unit
Unit Price (THB)
Discount (THB)
จำนวนเงิน
Amount (THB)
1
ชุดกล่องของขวัญ Premium Set
เก
5
ชุด
950.00
250.00
4,500.00
2 แก้วน้ำสแตนเลส สีชมพู 500 ml
20
ใบ
350.00
0.00
7,000.00
3 สมุดโน้ตปกหนัง PU
15
เล่ม
180.00
150.00
2,550.00
4
ปากกาลูกลื่น รุ่น Blossom
50
ก้าม
45.00
0.00
2,250.00
5
ถุงผ้าสกรีนโลโก้ ขนาด M
30
ใบ
2
60.00
300.00
1,500.00
รวมเป็นเงิน / Subtotal
18,800.00
หมายเหตุ / Remark
1. ราคานี้รวมค่าจัดส่งเรียบร้อยแล้ว
2. สินค้าไม่สามารถเปลี่ยนหรือคืนได้ ยกเว้นกรณีสินค้าชำรุดจากการผลิต
3. หากมีข้อสงสัย กรุณาติดต่อฝ่ายบริการลูกค้า โทร. 053-214-789 ต่อ 101
Thank you OR YOUR SUPPORT
ช่องทางการชำระเงิน / Payment Method
จำนวนเงินรวมทั้งสิ้น
Grand Total
สแกนเพื่อชำระเงิน
Scan to Pay
หัก ส่วนลดรวม / Total Discount
700.00
มูลค่าสินค้าหลังหักส่วนลด
18,100.00
ภาษีมูลค่าเพิ่ม (VAT 7%)
1,267.00
19,367.00
ธนาคารกสิกรไทย จำกัด (มหาชน)
KASIKORNBANK PCL.
เลขที่บัญชี 987-6-54321-0
ชื่อบัญชี บริษัท บลูมแอนด์โค ไลฟ์สไตล์ จำกัด
ขอบคุณที่ไว้วางใจในสินค้าและบริการของเรา
Prompt Pay
ขอแสดงความนับถือ
P.J.
(น.ส. ปรียาภรณ์ ใจดี )
ผู้มีอำนาจลงนาม
Authorized Signature
BLOOMING HAPPINESS IN EVERYDAY LIFE
"""

# The สิงโต invoice from the live app. Its totals box labels the pre-VAT
# goods total "ราคารวม" — a wording nothing recognised, so ยอดก่อนภาษี came
# back empty; and with the two labels "ภาษีมูลค่าเพิ่ม (7%)" and "รวมทั้งสิ้น"
# stacked ABOVE their three figures, the forward search for the total
# stopped at the first number below it and recorded the VAT, 4,200, as the
# grand total. The same words head the last column of the items table
# ("จำนวน" / "ราคา/หน่วย" / "ราคารวม"), which is the reason a bare "ราคารวม"
# was not already a keyword.
REAL_SINGTO_RAW_TEXT = """ใบเสร็จรับเงิน/ใบกำกับภาษี
บริษัท สิงโต จำกัด (สำนักงานใหญ่)
23/1 ต.สุเทพ อ.เมือง จ.เชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษี 0105562123454
ชื่อลูกค้า
บริษัท กากา จำกัด
ที่อยู่
เลขผู้เสียภาษี
123/6 ต.เชียงคาน อ.เชียงคาน จ.เลย 42110
1234567890888
เลขที่
77890
วันที่
25/08/2025
ล่าดับ
รายการสินค้า
จำนวน
ราคา/หน่วย
ราคารวม
1
ออกแบบผลิตภัณฑ์ (โลโก้งานวิ่ง)
2
30,000
60,000
หมายเหตุ
จำนวนเงินรวมทั้งสิ้น
การชำระเงิน
O เงินสด
O บัตรเดบิต/บัตรเครดิต
O โอนผ่านบัญชี
Downl
(เบนจามิน ชาห์)
วันที่
หมายเหตุ
ราคารวม
60,000
ภาษีมูลค่าเพิ่ม (7%)
รวมทั้งสิ้น
4,200
64,200
64,200
(หกหมื่นสี่พันสองร้อยบาทถ้วน)
อนุมัติโดย
22
รับชาระ
(คิมเบอร์ลี แมค)
วันที่
"""

# The แบร์ เกียร์ invoice from the live app. Its document box was emitted
# as a label column and a value column far apart, with the CUSTOMER box
# and the entire items table threaded between them:
#
#     เลขที่/ Invoice No ... ที่อยู่ / Address ... 456/89 ถนนสุขุมวิท ...
#     วันที่ / Date ... อีเมล / Email ... ล่าดับ ... HDD External 2TB ...
#     ครบกำหนด / Due Date / 01210 / 1 มีนาคม 2568 / 1 เมษายน 2568
#
# No two labels were ever adjacent, so the box yielded nothing and the
# forward search for the number walked into the buyer's address and
# returned "456/89"; the date was 16 lines from its label and came back
# empty. The buyer label's English half is glued to the name with no
# punctuation ("ชื่อลูกค้า / Customer บริษัท C จำกัด"), so "Customer" stayed
# stuck to the front of the recorded name.
REAL_BEARGEAR_RAW_TEXT = """BEAR GEAR
IT SYSTEM
บริษัท แบร์ เกียร์ ไอที ซิสเต็ม จำกัด
Bear Gear IT System Co., Ltd.
99/15 ถนนรัชดาภิเษก แขวงห้วยขวาง เขตห้วยขวาง กรุงเทพมหานคร 10310
เลขประจำตัวผู้เสียภาษี : 0105568034567 (สำนักงานใหญ่)
อีเมล : @BGearsite.com
ชื่อลูกค้า / Customer บริษัท C จำกัด
เลขที่/ Invoice No
ที่อยู่ / Address
456/89 ถนนสุขุมวิท ตำบลบางเมือง อำเภอเมืองสมุทรปราการ
จังหวัดสมุทรปราการ 10270
วันที่ / Date
เลขประจำตัวผู้เสียภาษี 0115569345678
อีเมล / Email
@Ccompany.com
ล่าดับ
No.
รายการสินค้า
Description
1
HDD External 2TB
2
RAM DDR4 16GB
ครบกำหนด / Due Date
01210
1 มีนาคม 2568
1 เมษายน 2568
เงื่อนไขชาระเงิน / Terms เครดิต 31 วัน
อ้างอิง / Reference
REF-2568-03
Invoice
ใบกำกับภาษี
ต้นฉบับ / ORIGINAL
จำนวน
Quantity
หน่วย
Unit
ราคา/หน่วย
Unit Price
ราคารวม
Amount
1
ชน
5,500.00
5,500.00
1
ชิ้น
1,500.00
1,500.00
หมายเหตุ / Remark
1. กรุณาตรวจสอบรายการสินค้าและจำนวนเงินให้ถูกต้องก่อนชำระเงิน
2. หากมีข้อสงสัยเกี่ยวกับใบกำกับภาษีนี้ กรุณาติดต่อผู้ออกเอกสารตามอีเมลด้านบน
จำนวนเงินรวมทั้งสิ้น
Grand Total
ราคารวม / Subtotal
7,000.00
ภาษีมูลค่าเพิ่ม (7%) / VAT
490.00
0.00
ส่วนลด / Discount
7,490.00
(เจ็ดพันสี่ร้อยเก้าสิบบาทถ้วน )
ช่องทางการชาระเงิน / Payment
ชื่อบัญชี
เลขที่บัญชี
BGear.inc
022-222-2222
BEAR GEAR IT SYSTEM
คุณธนกร วัฒนกิจ
ผู้รับสินค้า
(Received by)
ขอบคุณที่ใช้บริการ
Thank you for your business
คุณศิริพร แสงทอง
ผู้มีอำนาจลงนาม
กรรมการบริษัท (Authorized Signature)
@BGearsite.com
"""

# A second แบร์ เกียร์ invoice. Here the document box's labels DID come out
# as a run, so the by-order fallback was never reached — and the run of
# values behind them was cut off after its first entry, because the two
# that follow are dates spelled out in Thai ("1 กุมภาพันธ์ 2568") and only
# the by-order fallback knew that shape. One value against four labels
# still paired soundly as a document number, so the invoice came through
# with its number and no date at all.
REAL_BEARGEAR2_RAW_TEXT = """BEAR GEAR
IT SYSTEM
บริษัท แบร์ เกียร์ ไอที ซิสเต็ม จำกัด
Bear Gear IT System Co., Ltd.
99/15 ถนนรัชดาภิเษก แขวงห้วยขวาง เขตห้วยขวาง กรุงเทพมหานคร 10310
เลขประจำตัวผู้เสียภาษี : 0105568034567 (สำนักงานใหญ่)
อีเมล : @BGearsite.com
ชื่อลูกค้า / Customer บริษัท C จำกัด
ที่อยู่ / Address
456/89 ถนนสุขุมวิท ตำบลบางเมือง อำเภอเมืองสมุทรปราการ
จังหวัดสมุทรปราการ 10270
เลขประจำตัวผู้เสียภาษี 0115569345678
อีเมล / Email
@Ccompany.com
ล่าดับ
No.
รายการสินค้า
Description
1
SSD 500GB
2
SSD 1TB
เลขที่/ Invoice No
วันที่ / Date
ครบกำหนด / Due Date
เงื่อนไขชาระเงิน / Terms
อ้างอิง / Reference
01210
1 กุมภาพันธ์ 2568
1 มีนาคม 2568
เครดิต 28 วัน
REF-2568-02
Invoice
ใบกำกับภาษี
ต้นฉบับ / ORIGINAL
จำนวน
Quantity
หน่วย
Unit
ราคา/หน่วย
Unit Price
ราคารวม
Amount
1
ชน
2,500.00
2,500.00
1
ชิ้น
3,500.00
3,500.00
หมายเหตุ / Remark
1. กรุณาตรวจสอบรายการสินค้าและจำนวนเงินให้ถูกต้องก่อนชำระเงิน
2. หากมีข้อสงสัยเกี่ยวกับใบกำกับภาษีนี้ กรุณาติดต่อผู้ออกเอกสารตามอีเมลด้านบน
จำนวนเงินรวมทั้งสิ้น
Grand Total
ราคารวม / Subtotal
ภาษีมูลค่าเพิ่ม (7%) / VAT
ส่วนลด / Discount
ช่องทางการชาระเงิน / Payment
ชื่อบัญชี
เลขที่บัญชี
BGear.inc
022-222-2222
BEAR GEAR IT SYSTEM
ขอบคุณที่ใช้บริการ
Thank you for your business
คุณธนกร วัฒนกิจ
ผู้รับสินค้า
(Received by)
2
คุณอนุชา ทองดี
ผู้มีอำนาจลงนาม
ผู้จัดการฝ่ายขาย (Authorized Signature)
6,000.00
420.00
0.00
6,420.00
( หกพันสี่ร้อยยี่สิบบาทถ้วน )
@BGearsite.com
"""

# A second scan of the สิงโต invoice. OCR put a space either side of each
# slash in its date — "25 /08/ 2025" — which matched no date pattern at
# all, so the invoice came through with no date.
REAL_SINGTO2_RAW_TEXT = """ใบเสร็จรับเงิน/ใบกำกับภาษี
บริษัท สิงโต จำกัด (สำนักงานใหญ่)
23/1 ต.สุเทพ อ.เมือง จ.เชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษี 0105562123454
ชื่อลูกค้า
บริษัท กากา จำกัด
เลขที
77890
ที่อยู่
123/6 ต.เชียงคาน อ.เชียงคาน จ.เลย 42110
วันที่
25 /08/ 2025
เลขผู้เสียภาษี
1234567890888
ล่าดับ
รายการสินค้า
จำนวน
ราคา/หน่วย
ราคารวม
1
ออกแบบผลิตภัณฑ์ (โลโก้งานวิ่ง)
2
30,000
60,000
หมายเหตุ
จำนวนเงินรวมทั้งสิ้น
การชำระเงิน
เงินสด
บัตรเดบิต / บัตรเครดิต
O โอนผ่านบัญชี
วันที่
De
(เบนจามิน ชาห์)
หมายเหตุ
ราคารวม
60,000
ภาษีมูลค่าเพิ่ม (7%)
รวมทั้งสิ้น
4,200
64,200
64,200
(หกหมื่นสี่พันสองร้อยบาทถ้วน)
อนุมัติโดย
รับชำระ
(คิมเบอร์ลี แมค)
วันที่
"""

# A third JP invoice. Its document box is preceded by an empty strip of
# labels ("เลขที่ใบสั่งซี้อ/Order No.", "พนักงานขาย/Salesman",
# "กำหนดชาระ/Due Date") whose values are all blank, so the label run held
# five labels against the box's two values and could not pair. The scan
# for a matching value run then carried on DOWNWARD past the items-table
# heading, reached the first item row, and paired the run "6" / "10" /
# "130.-" with them — filing the invoice under the number "130.-" while
# the real one, IV6801224-125, sat two lines below its own label.
REAL_JP3_RAW_TEXT = """JP
บริษัท โจธนารักษ์ แพตเดอร์สัน จำกัด (สำนักงานใหญ่)
123/69 ถนนฉลองกรุง แขวงลาดกระบัง เขตลาดกระบัง กรุงเทพฯ 10520
เลขประจำตัวผู้เสียภาษี 0105576890143
โทร. 020-5345-678 /แฟกซ์. 026-9267-00
ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด
ที่อยู่/Address : 99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษี/TAX ID : 0105569123456
เลขที่ใบสั่งซี้อ/Order No.
พนักงานขาย/Salesman
กำหนดชาระ/Due Date
ใบกำกับภาษี/ใบเสร็จรับเงิน
TAX INVOICE/RECEIPT
เลขที่/No.
วันที่/Date.
**ต้นฉบับ/Original**
IV6801224-125
24/12/68
รหัสลูกค้า/Customer Code : 7820-12
ล่าดับ
รายการ
จำนวน
ราคา
ราคาสุทธิ
1.
สีนํ้า
6
10
130.-
1,300.-
2.
กระดาษ (200 แกรม, A3)
20
35.-
700.-
หมายเหตุ
000
ราคารวมสินค้า (บาท)
2,000.-
(สองพันหนึ่งร้อยสี่สิบบาทถ้วน)
ภาษีมูลค่าเพิ่ม (VAT) 7%
จำนวนเงินทั้งสิ้น (บาท)
140.-
2,140.-
การชาระเงิน/Payment
เงินสด Cash
โอนเข้าบัญชี Tanter.No..
เช็ค Chesue.No..
วันที่/Date
ในนามบริษัท โจธนารักษ์ แพตเดอร์สัน จำกัด
ผู้มีอานาจลงนาม
.....................
ลงนามพนักงานรับเงิน
(วันที
..)
ลงนามพนักงานส่งของ
......................
"""

# The มั่งมีศรีสุข invoice for March. Its totals box has FIVE rows, but the
# grand total's label ("รวมมูลค่าสุทธิ") was emitted after the first three
# figures, leaving a run of four labels —
#
#     สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม / สินค้าที่เสียภาษีมูลค่าเพิ่ม /
#     ภาษีมูลค่าเพิ่ม VAT 7% / หัก เงินมัดจำ
#
# — against only three figures (0.00 / 5,500.00 / 385.00). A label run
# longer than its value run had no handling at all, so it was skipped
# whole; the next starting point, one label shorter, matched the count
# exactly and was taken without question, pairing every figure one row
# out: the exempt 0.00 became ยอดก่อนภาษี and the subtotal became the VAT.
REAL_MUNGMEE_MAR_RAW_TEXT = """มศส
เลขประจำตัวผู้เสียภาษีอากร
0105568000222
บริษัท มั่งมีศรีสุข จำกัด (สำนักงานใหญ่)
MUNGMEE SRISUK CO., LTD. (Head Office)
88/8 อาคารมั่งมีศรีสุข ชั้น 12 ถนนรัชดาภิเษก แขวงห้วยขวาง เขตห้วยขวาง กรุงเทพมหานคร 10310
88/8 Mungmee Srisuk Building, 12th Floor, Ratchadaphisek Rd., Huai Khwang, Bangkok 10310
โทร./Tel. 02-988-1234 E-mail : sales@mungmeesrisuk.example
ใบเสร็จรับเงิน / ใบกำกับภาษี
RECEIPT / TAX INVOICE
งวดประจำเดือนมีนาคม 2568
นามผู้ชื้อ / Name
บริษัท A จำกัด
ที่อยู่ / Address
99/15 ถนนวิภาวดีรังสิต แขวงจอมพล เขตจตุจักร กรุงเทพมหานคร 10900
เลขประจำตัวผู้เสียภาษีอากร / Tax ID
0105569123456
เลขที่/NO
วันที่ / DATE
เครดิต / CREDIT
วันครบกำหนด / DUE DATE
เลขที่ใบสั่งซื้อ / PO.NO
พนักงานขาย / SALEMAN
รหัสลูกค้า / CUSTOMER
INV-2568-03
31/03/2568
30 วัน
30/04/2568
PO-2568-0305
อรทัย สุขใจ
CUS-0088
ล่าดับที
ITEM
1
สมุดบันทึกปกหนัง
2
ปากกาลูกลื่น
รายการ
DESCRIPTION
จำนวน
หน่วยนับ
ราคาต่อหน่วย
V/N*
QUANTITY
UNIT
UNIT PRICE
ส่วนลดต่อหน่วย
DISCOUNT
หมายเหตุ * (V ภาษีมูลค่าเพิ่ม / N ยกเว้นภาษีมูลค่าเพิ่ม)
จำนวนเงินรวม (ตัวอักษร)
GRAND TOTAL (ALPHABET)
ห้าพันแปดร้อยแปดสิบห้าบาทถ้วน
<
10
40
เล่ม
95.00
10.00
หน้าที่ 1/1
จำนวนเงินบาท
AMOUNT (BAHT)
3,400.00
V
300
ด้าม
8,00
1.00
2,100,00
- สินค้าตามใบกำกับภาษีนี้ แม้จะส่งมอบแก่ผู้ซื้อแล้วก็ยังคงเป็นทรัพย์สินของผู้ขายจนกว่าผู้ซื้อได้ชำระเงินเรียบร้อยแล้ว
- โปรดสั่งจ่ายเช็คขีดคร่อมในนาม "บริษัท มั่งมีศรีสุข จำกัด เท่านั้น
- การชำระเงินด้วยเช็คจะสมบูรณ์ต่อเมื่อได้รับเงินตามเช็คเรียบร้อยแล้ว
- ถ้าสินค้าไม่ถูกต้องโปรดแจ้งกลับภายใน 7 วัน หากเกินกำหนดทางบริษัทขอสงวนสิทธิ์ในการเปลี่ยนหรือคืน
- สินค้าหมวดเครื่องเขียนรับประกันคุณภาพ 30 วันนับจากวันที่ส่งมอบ
สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม
สินค้าที่เสียภาษีมูลค่าเพิ่ม
ภาษีมูลค่าเพิ่ม VAT 7%
หัก เงิน จ่า
0.00
5,500.00
385.00
รวมมูลค่าสุทธิ
บริษัท มั่งมีศรีสุข จำกัด
ผู้มีอำนาจลงนาม
AUTHORIZED SIGNATURE
0.00
5,885,00
"""

# The พรีเมียร์ คลีน invoice from the live app. The customer block is
# printed ABOVE the letterhead, and both parties state a taxpayer ID. The
# customer box was judged line by line — "is there a buyer label just
# above, with no other company named in between" — which broke on the
# buyer's OWN name: "รายละเอียดลูกค้า" / "บริษัท B จำกัด" / two address
# lines / the buyer's ID. Scanning up from that ID reached "บริษัท B
# จำกัด", took it for the next party, judged the ID to be outside the
# customer box, and filed the CUSTOMER's 0505569234567 as the issuer's.
REAL_PREMIERCLEAN_RAW_TEXT = """ใบเสร็จรับเงิน/ใบกำกับภาษี
เลขที่ 000125
วันที่ 31/1/2025
รายละเอียดลูกค้า
บริษัท B จำกัด
188 หมู่ 7 ถนนเชียงใหม่-ลำพูน ตำบลหนองผึ้ง อำเภอสารภี
จังหวัดเชียงใหม่ 50140
เลขประจำตัวผู้เสียภาษี 0505569234567
บริษัท พรีเมียร์ คลีน เซอร์วิส จำกัด
125/8 ถนนเชียงใหม่-ลำพูน ตำบลหนองหอย อำเภอ
เมืองเชียงใหม่ จังหวัดเชียงใหม่ 50000
โทร 087-5693687
เลขประจำตัวผู้เสียภาษี 0115569000012
ล่าดับ
รายการ
จำนวน ราคาต่อหน่วย
จำนวนเงิน
ค่าบริการทำความสะอาดสำนักงาน
1
ประจำเดือน มกราคม
2
ค่าอุปกรณ์และน้ำยาทำความสะอาด
จำนวนเงินรวมทั้งสิ้น(ตัวอักษร) : หนึ่งพันเก้าร้อยยี่สิบหกบาทถ้วน
1
1,500.00
1,500.00
300.00
300.00
รวมราคา
ภาษีมูลค่าเพิ่ม 7%
รวมทั้งสิ้น
1,800.00
126.00
1,926.00
ริชาร์ด ซันเชซ
ผู้มีอำนาจลงนาม
ชำระโดย
เงินสด
โอนเงิน
ธนาคาร ABC เลขที่ 0123 45678901
จำนวนเงิน 1,926.00 บาท เวลา 14.23 น.
ไอริน แสนสุข
ผู้รับเงิน
วันที่ 31/1/2025
"""

# A Makro POS receipt — the format that dominates the user's batch (15 of
# 60 pages). Three separate defects, all of them silent.
# (1) Its totals row is labelled "ราคาสินค้า / ภาษี / รวม" — three words
#     far too generic to be keywords — so the totals block matched the
#     ITEMS table's "มูลค่าสินค้า" heading instead and paired it with the
#     first item row: a 356.00 receipt was filed as 96.00 + 1.00 VAT. The
#     arithmetic scan HAD the right answer all along (332.71 + 23.29 =
#     356.00, and 23.29 is exactly 7% of 332.71) but was locked out,
#     because a figure paired with a label used to be treated as proof.
# (2) A reissued receipt names the document it replaces — "เป็นการยกเลิก
#     และออกใบกำกับภาษีฉบับใหม่ แทนฉบับเดิมเลขที่ 041030406649" — and that
#     CANCELLED number was recorded as this receipt's own.
# (3) The receipt's real number sits in a column-major header box
#     ("แผ่นที่ / เลขที่ใบเสร็จ / พนักงานเก็บเงิน / วันที่" then their four
#     values), which no document-box label matched; and once it did, the
#     12-digit number was thrown away by a rule meant to reject 13-digit
#     taxpayer IDs.
REAL_MAKRO_RAW_TEXT = """บริษัท ซีพี เอ็กซ์ตร้า จำกัด (มหาชน)
สำนักงานใหญ่ โทร. 020678999
เลขประจำตัวผู้เสียภาษีอากร 0107567000414
makro
โปรดทราบ
1 โปรดเก็บใบเสร็จไว้เป็นหลักฐาน
2. การติดต่อกับทางบริษัท โปรดนำใบเสร็จมาทุกครั้ง
3 บริษัทจะรับคืนสินค้าภายใน 7 วัน
ยกเว้นของสดรับคืนภายในวันที่ซื้อ
4 สินค้าที่รับคืนต้องอยู่ในสภาพเดิม
เป็นการยกเลิกและออกใบกำกับภาษีฉบับใหม่ แทนฉบับเดิมเลขที่ 041030406649
สาขาที่ 00042 สาขาเชียงใหม่ 2 : 191 หมู่ที่ 7 ต.แม่เหียะ
7
อ.เมืองเชียงใหม่ จ.เชียงใหม่ 50100
โทร.053-447799 โทรสาร 053-447804-5
POS ID#
คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่ สำนักงานใหญ่
ใบเสร็จรับเงิน/ใบกำกับภาษี
239 ถ.ห้วยแก้ว
Customer Name
ต.สุเทพ อ.เมืองเชียงใหม่
ชื่อสมาชิก
จ.เชียงใหม่ 50200
Customer No.
เลขที่สมาชิก
041 999999
TAX ID# 0994000423179
Time
17:16
เวลา
แผ่นที่
Recejpt Ng
เลขที่ใบเสร็จ
Cashier
พนักงานเก็บเงิน
Date
วันที่
1
041501408013
111 3
22-07-2025
QUANTITY OR
ARTICLE
WEIGHT
NUMBER
รหัสสินค้า
จำนวน/นํ้าหนัก
1 8852008300017 โคอะลามาร์ช ไส้ช็อกโกแลต 370x6
ARTICLE DESCRIPTION
รายการสินค้า
UNIT
PACKS
PACK
PRICE
VAT
CODE
VALUE INCLUDED VAT
หน่วยบรรจุ
ราคา(บาท) รหัส ภ.พ.
มูลค่าสินค้า
รวม VAT (บาท)
6 ชร
96.00
2
96.00
1
8851019910307 ป๊อกกี้ รสช็อกโกแลต200X10
10 ชร
80.00
2
80.00
1 18859400301922 ซันซุเยลลี่พืช&ลิ้นจี่ 960X6
6 หอ
129.00
2
129.00
1
8850425007281 ยูโร่ช็อกโกพาย ไส้แยมราส 170X12
12 ชร
51.00
2
51.00
356.00
ชำระโดย
TID: 041003
QR KBANK
TRACE : KB000001834687
BATCH : CRP0000235
REF NO: APIC17531793840131TT
จำนวน
ชิ้น
รหัส ภ.พ.%
ราคาสินค้า
LEGAL AMOUNT
ภาษี
รวม
รวมเงิน
4
2 7.00
TOTAL
332.71
23.29
356.00
CASH
356.00
356.00
332.71
23.29
356.00
ทอน
0.00-
ยอดเงินชำระ
makro
ทาทา เชียงใหม่
บุนจา
356.00
"""
















# ใบจริง B2S — หน้า 58 ของกอง "ใบจริงอันใหม่.pdf" ผู้ใช้อัปโหลดเข้าเว็บจริง
# แล้วอ่านยอดผิดทั้งสามช่อง ข้อความนี้คือที่ Cloud Vision คายออกมาจริง
#
# กล่องยอดของใบนี้โดน OCR ฉีกเป็นชิ้น: ป้ายสี่บรรทัดมาก่อน ตามด้วยแถว
# ":" สี่บรรทัด แล้วค่าของมันถูกสลับฟันปลากับคอลัมน์วิธีชำระเงินที่อยู่
# ข้าง ๆ กลายเป็น
#     ส่วนลด / รวมเงิน / 0.00 / 52.00 / ชำระโดย / 0.00 /
#     QRPP 114100XXXXXX6 / 52.00 / 52.00 / Change / 0.00 / 48.60 / 3.40
# ไม่มีป้ายไหนได้เจอค่าของตัวเอง และไม่มีชุดตัวเลขสามตัวที่ติดกันชุดไหน
# ใช้ได้เลย ทั้งที่ 48.60 + 3.40 = 52.00 อยู่ครบบนหน้านั้น
#
# ผลบนหน้าเว็บก่อนแก้: ยอดก่อนภาษี 52 / VAT 114,100 / ยอดรวม ว่าง
#   - 52 มาจากป้าย "รวมเงิน" ซึ่งจับคู่กับค่าผิดตัว
#   - 114,100 คือเลขบัตรที่ถูกปิดบางส่วนใน "QRPP 114100XXXXXX6"
#   - ยอดรวมว่าง เพราะไม่มีป้ายยอดรวมให้จับเลย
REAL_B2S_RAW_TEXT = """B2S
บริษัท บีทูเอส จำกัด สาขาโรบินสันเชียงใหม่ สาขาที่ 00053
หน้าที่ 1/1
เลขที่ 9 หมู่ 3 ตำบลสุเทพ อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษีอากร : 0105538032743
เลขที่
50051072510000079
วันที่
22 กรกฎาคม 2568
ใบเสร็จรับเงิน/ใบกำกับภาษี
เป็นการยกเลิกใบกำกับภาษีอย่างย่อเลขที่ 103-107827 วันที่ 22 กรกฎาคม 2568 และออกใบกำกับภาษีอิเล็กทรอนิกส์ใหม่แทน
ชื่อ คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่
สาขาที่ 00120
ที่อยู่ เลขที่ 239 ถนนห้วยแก้ว ตำบลสุเทพ อำเภอ เมืองเชียงใหม่ จังหวัด เชียงใหม่ 50200
ลำดับที่ รหัสสินค้า
ชื่อสินค้า
1
V 8850968601113
SBกระดาษปรู๊ฟขาว P10
รวม
เลขประจำตัวผู้เสียภาษีอากร 0994000423179
จำนวน
ราคา
จำนวนเงิน
1.00
52.00
52.00
TP No. 103-115862
662025072250051103115862
1
52.00
(ห้าสิบสองบาทถ้วน)
- มูลค่าสินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม
มูลค่าสินค้าที่รวมภาษีมูลค่าเพิ่ม
- มูลค่าสินค้าที่เสียภาษีมูลค่าเพิ่ม
- ภาษีมูลค่าเพิ่ม
:
:
:
:
ส่วนลด
รวมเงิน
0.00
52.00
ชำระโดย
0.00
QRPP 114100XXXXXX6
52.00
52.00
Change
0.00
48.60
3.40
หมายเหตุ : ใบเสร็จรับเงินฉบับนี้จะสมบูรณ์ เมื่อบริษัทได้รับเงินเรียบร้อยแล้วเท่านั้น
V = สินค้าที่คิดภาษีมูลค่าเพิ่ม, N = = สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม
ใบเสร็จรับเงิน/ใบกำกับภาษีฉบับนี้ได้จัดทำขึ้นอย่างสมบูรณ์แล้วโดยไม่ต้องมีลายเซ็นของเจ้าหน้าที่บริษัทแต่อย่างใด
เงื่อนไขการรับเปลี่ยนคืนสินค้า
รับเปลี่ยนหรือคืนสินค้าในสภาพสมบูรณ์ พร้อมใบเสร็จต้นฉบับภายใน 14 วันนับจากวันและสาขาที่ซื้อเท่านั้น (รายละเอียดสินค้าที่ไม่สามารถเปลี่ยนคืนได้ กรุณาตรวจสอบ ณ จุดขาย)
เงื่อนไขการการแก้ไขใบกำกับภาษีเต็มรูป
หากต้องการแก้ไขใบเสร็จรับเงินหรือใบกำกับภาษี กรุณาติดต่อทางห้างฯ ภายใน 1 วันทำการ นับจากวันได้รับเอกสาร หากพ้นกำหนด ทางห้างฯ จะไม่รับผิดชอบใดๆ ทั้งสิ้น
เอกสารนี้ได้จัดทำและส่งข้อมูลให้แก่กรมสรรพากรด้วยวิธีการทางอิเล็กทรอนิกส์
"""


# ใบจริง เป๋าเปา — หน้า 50 ของกอง "ใบจริงอันใหม่.pdf" ข้อความดิบจาก Cloud Vision
#
# ใบนี้อ่านถูก 8 ใน 9 ช่อง ผิดแค่ชื่อผู้ซื้อ ซึ่งกลายเป็นชื่อสินค้า
# "กระดาษAA 80แกรม 1*100(453)" — สองเหตุซ้อนกัน:
#
#   1. คำใบ้ว่าบรรทัดนี้เป็นชื่อองค์กรมีคำว่า "กรม" (หน่วยงานราชการ) อยู่
#      ด้วย และภาษาไทยไม่เว้นวรรคระหว่างคำ มันจึงไปตรงกับ "80แกรม"
#   2. การสแกนหาชื่อผู้ซื้อใต้ป้ายเดินลงไปเก้าบรรทัด ข้ามหัวตาราง
#      "รายการสินค้า" เข้าไปกลางตารางสินค้า
#
# และกล่องลูกค้าของใบนี้ยังกลับหัวด้วย — OCR คายค่าออกมา "ก่อน" ป้ายของมัน
#     เลขประจำตัวผู้เสียภาษี : 0-9940-00423-17-9
#     คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่   <- ค่า
#     ชื่อ                                  <- ป้ายของค่าข้างบน
#     ที่อยู่                                <- ป้ายของค่าข้างล่าง
#     239 ถ.ห้วยแก้ว ต.สุเทพ
# การค้นแบบ "หาบรรทัดที่หน้าตาเหมือนชื่อองค์กรที่ใกล้ป้ายที่สุด" รับมือได้
# อยู่แล้ว ขอแค่การสแกนลงล่างอย่าไปคืนค่าผิด ๆ มาก่อน
REAL_PAOPAO_RAW_TEXT = """IIII
Shop
ห้างหุ้นส่วนจำกัด เป่าเปา (สำนักงานใหญ่ )
เลขประจำตัวผู้เสียภาษี : 0-5035-50005-30-5
109 หมู่ 10 ต.ป่าแดด อ.เมือง จ.เชียงใหม่ 50100
โทร : 053-273815-7,085-6940220
เลขประจำตัวผู้เสียภาษี : 0-9940-00423-17-9
คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่
ชื่อ
ที่อยู่
239 ถ.ห้วยแก้ว ต.สุเทพ
อ.เมือง จ.เชียงใหม่ 50200
No. รหัสสิน
1 1912300218
2 8856976000597
รายการสินค้า
พวงกุญแจ ลายการ์ตูนคละแบบ
กระดาษAA 80แกรม 1*100(453)
3 8851552203614 ปากกาเคมี 2 หัว Horse น้ำเงิน+แดง
ใบเสร็จรับเงิน / ใบกำกับภาษี
(เอกสารออกเป็นชุด )
หน้าที่ 1 พิมพ์ 16:34:40 22/07/2025
วันที่ใบกำกับภาษี 22/07/2568
เลขที่ใบกำกับภาษี POSS6807/2233
จำนวน หน่วยนับ ราคา/หน่วย
จำนวนเงิน
1 โหล×12
165.00
165.00
1 ชื้น
45.00
45.00
1 โหลx12
130.00
130,00
รวมจำนวนชิ้น
มูลค่าสินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม
# คือ สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม
มูลค่าสินค้าที่เสียภาษีมูลค่าเพิ่ม
ภาษีมูลค่าเพิ่ม 7%
รวมหน้านี
รวม
340.00
340.00
3.00
317.76
0.00
22.24
มูลค่าสินค้า
317.76
มูลค่าสินค้ารวม
ส่วนลดสมาชิก
ส่วนลดคูปอง
ส่วนลด
ค่าธรรมเนียม
340.00
0.00
0.00
0.00
0.00
ตัวหนังสือ : (สามร้อยสี่สิบบาทถ้วน)
000602287937
วัน
ผู้จัดทา / ผู้พิมพ์
วันที่ 22/07/2568
มูลค่าสินค้าสูทธิ์
Den
ผู้รับเงิน
วันที่ 22/07/2568
340.00
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

    # regression: the second บาบาร่า invoice (see REAL_BARBARA2_RAW_TEXT) —
    # a value that starts inside the keyword window but ends outside it must
    # not be truncated at the boundary.
    fields9 = extractor.extract_fields(REAL_BARBARA2_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real บาบาร่า #2 OCR text fields ---")
    for k, v in fields9.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real barbara2: invoice_no = IV20250504-012 (not truncated to IV20250504)",
        fields9["invoice_no"] == "IV20250504-012",
    )
    all_ok &= check("real barbara2: date = 2025-05-24", fields9["invoice_date_iso"] == "2025-05-24")
    all_ok &= check("real barbara2: subtotal = 2827.1", fields9["subtotal"] == 2827.10)
    all_ok &= check("real barbara2: vat = 197.9", fields9["vat"] == 197.90)
    all_ok &= check("real barbara2: total = 3025.0", fields9["total"] == 3025.00)
    all_ok &= check("real barbara2: buyer_name", fields9["buyer_name"] == "บริษัท A จำกัด")
    all_ok &= check("real barbara2: not flagged for review", fields9["needs_review"] is False)

    # regression: the มั่งมีศรีสุข invoice (see REAL_MUNGMEE_RAW_TEXT) — four
    # independent failures in one document
    fields10 = extractor.extract_fields(REAL_MUNGMEE_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real มั่งมีศรีสุข OCR text fields ---")
    for k, v in fields10.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real mungmee: invoice_no = INV-2568-01 (label lost its tone mark)",
        fields10["invoice_no"] == "INV-2568-01",
    )
    all_ok &= check(
        "real mungmee: classified เต็มรูป (was downgraded to ย่อ)",
        fields10["doc_type"] == "เต็มรูป",
    )
    all_ok &= check("real mungmee: subtotal = 15750.0", fields10["subtotal"] == 15750.00)
    all_ok &= check("real mungmee: vat = 1102.5", fields10["vat"] == 1102.50)
    all_ok &= check("real mungmee: total = 16852.5 (was 1)", fields10["total"] == 16852.50)
    all_ok &= check("real mungmee: date = 2025-01-31", fields10["invoice_date_iso"] == "2025-01-31")
    all_ok &= check("real mungmee: seller tax id", fields10["seller_tax_id"] == "0105568000222")
    all_ok &= check("real mungmee: buyer_name", fields10["buyer_name"] == "บริษัท A จำกัด")
    all_ok &= check("real mungmee: not flagged for review", fields10["needs_review"] is False)

    # a comma standing in for the decimal point
    all_ok &= check("'15,750,00' parses as 15750.0", extractor._clean_number("15,750,00") == 15750.0)
    all_ok &= check("'1,102,50' parses as 1102.5", extractor._clean_number("1,102,50") == 1102.5)
    all_ok &= check("'0,00' parses as 0.0", extractor._clean_number("0,00") == 0.0)
    all_ok &= check("'1,234' is still one thousand two hundred",
                    extractor._clean_number("1,234") == 1234.0)
    all_ok &= check("'12,345,678' is still twelve million",
                    extractor._clean_number("12,345,678") == 12345678.0)
    all_ok &= check("'2,571.03' still parses", extractor._clean_number("2,571.03") == 2571.03)

    # VATable vs exempt goods lines, and the labels that keep a totals block
    # aligned with its values
    all_ok &= check(
        "'สินค้าที่เสียภาษีมูลค่าเพิ่ม' is the subtotal, not the VAT",
        extractor._classify_totals_label("สินค้าที่เสียภาษีมูลค่าเพิ่ม") == "subtotal",
    )
    all_ok &= check(
        "'สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม' is neither subtotal nor VAT",
        extractor._classify_totals_label("สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม") == "exempt",
    )
    all_ok &= check(
        "'ภาษีมูลค่าเพิ่ม VAT7%' is still the VAT",
        extractor._classify_totals_label("ภาษีมูลค่าเพิ่ม VAT7%") == "vat",
    )
    all_ok &= check(
        "'รวมมูลค่าสุทธิ' is the total",
        extractor._classify_totals_label("รวมมูลค่าสุทธิ") == "total",
    )

    # regression: the ร่ำรวย888 invoice (see REAL_ROMRUAY_RAW_TEXT)
    fields11 = extractor.extract_fields(REAL_ROMRUAY_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real ร่ำรวย888 OCR text fields ---")
    for k, v in fields11.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real romruay: invoice_no = RE00001 (not the bank account 456-7-89012-3)",
        fields11["invoice_no"] == "RE00001",
    )
    all_ok &= check(
        "real romruay: date = 2025-01-31 (not the 21/01/2558 signature date)",
        fields11["invoice_date_iso"] == "2025-01-31",
    )
    all_ok &= check("real romruay: subtotal = 180000.0", fields11["subtotal"] == 180000.00)
    all_ok &= check("real romruay: vat = 12600.0", fields11["vat"] == 12600.00)
    all_ok &= check("real romruay: total = 192600.0", fields11["total"] == 192600.00)
    all_ok &= check("real romruay: buyer_name", fields11["buyer_name"] == "บริษัท A จำกัด")
    all_ok &= check("real romruay: seller tax id", fields11["seller_tax_id"] == "0105568345671")
    all_ok &= check("real romruay: classified เต็มรูป", fields11["doc_type"] == "เต็มรูป")
    all_ok &= check("real romruay: not flagged for review", fields11["needs_review"] is False)

    # amounts printed with their currency
    all_ok &= check("'183,800.00 บาท' parses", extractor._clean_number("183,800.00 บาท") == 183800.0)
    all_ok &= check("'1,500 THB' parses", extractor._clean_number("1,500 THB") == 1500.0)
    all_ok &= check(
        "'183,800.00 บาท' counts as a number line",
        bool(extractor.PURE_NUMBER_LINE_RE.match("183,800.00 บาท")),
    )

    # only a Thai/English label pair is one field; two Thai labels are two
    all_ok &= check(
        "'ภาษีมูลค่าเพิ่ม 7%' + 'VAT 7%' are one field",
        extractor._is_translation_pair("ภาษีมูลค่าเพิ่ม 7%", "VAT 7%"),
    )
    all_ok &= check(
        "'จำนวนเงินรวมทั้งสิ้น' + 'จำนวนรวมทั้งสิ้น' are two fields",
        extractor._is_translation_pair("จำนวนเงินรวมทั้งสิ้น", "จำนวนรวมทั้งสิ้น") is False,
    )

    # labels that name some OTHER number must not supply the invoice number
    for label, line in [("bank account", "เลขที่บัญชี"), ("reference", "เลขที่อ้างอิง"),
                        ("purchase order", "เลขที่ใบสั่งซื้อ")]:
        all_ok &= check(
            f"'{line}' is not treated as the invoice-number label ({label})",
            extractor.extract_invoice_no(f"{line}\n456-7-89012-3\n") is None,
        )
    all_ok &= check(
        "a plain 'เลขที่' label still supplies the invoice number",
        extractor.extract_invoice_no("เลขที่\nIV20250123-089\n") == "IV20250123-089",
    )

    # regression: the ฟาร์มเงินฟาร์มทอง invoice (see REAL_FARM_RAW_TEXT) —
    # seller and buyer names, which fail together
    fields12 = extractor.extract_fields(REAL_FARM_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real ฟาร์มเงินฟาร์มทอง OCR text fields ---")
    for k, v in fields12.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real farm: seller_name is the company, not the label 'ชื่อลูกค้า'",
        fields12["seller_name"] == "บริษัท ฟาร์มเงินฟาร์มทอง จำกัด",
    )
    all_ok &= check(
        "real farm: buyer_name = บริษัท A จำกัด (not the seller, Thai or English)",
        fields12["buyer_name"] == "บริษัท A จำกัด",
    )
    all_ok &= check("real farm: invoice_no = INV-2568-001", fields12["invoice_no"] == "INV-2568-001")
    all_ok &= check("real farm: date = 2025-01-31", fields12["invoice_date_iso"] == "2025-01-31")
    all_ok &= check("real farm: seller tax id", fields12["seller_tax_id"] == "0173568002246")
    all_ok &= check("real farm: subtotal = 38500.0", fields12["subtotal"] == 38500.00)
    all_ok &= check("real farm: vat = 2695.0", fields12["vat"] == 2695.00)
    all_ok &= check("real farm: total = 41195.0", fields12["total"] == 41195.00)
    all_ok &= check("real farm: classified เต็มรูป", fields12["doc_type"] == "เต็มรูป")
    all_ok &= check("real farm: not flagged for review", fields12["needs_review"] is False)

    # a bare field label is never a company name
    all_ok &= check(
        "seller search skips a label-only line",
        extractor.extract_seller_name("ชื่อลูกค้า\nCustomer Name\nที่อยู่\n"
                                      "บริษัท ฟาร์มเงินฟาร์มทอง จำกัด\n")
        == "บริษัท ฟาร์มเงินฟาร์มทอง จำกัด",
    )
    all_ok &= check(
        "an ALL-CAPS English company name is recognised as one",
        bool(extractor.COMPANY_NAME_HINT_RE.search("FARM NGERN FARM THONG CO., LTD.")),
    )
    all_ok &= check(
        "'บริษัท A จำกัด' is Thai script despite the letter A",
        extractor._is_latin_script("บริษัท A จำกัด") is False,
    )

    # regression: the March มั่งมีศรีสุข invoice INV-2568-03 — same template
    # as REAL_MUNGMEE_RAW_TEXT, but OCR spelled the buyer label correctly
    # this time ("นามผู้ซื้อ / Name", not "นามผู้ชื้อ"). The keyword therefore
    # matched, and the English half left on the line after it — "/ Name" —
    # was recorded as the buyer. The misspelled month's copy had masked
    # this: with no keyword match it reached the value by another route.
    march = extractor.extract_fields(
        REAL_MUNGMEE_RAW_TEXT
        .replace("นามผู้ชื้อ / Name", "นามผู้ซื้อ / Name")
        .replace("INV-2568-01", "INV-2568-03"),
        ocr_confidence=90.0,
    )
    all_ok &= check(
        "bilingual label: buyer is the value, not the label's English half",
        march["buyer_name"] == "บริษัท A จำกัด",
    )
    all_ok &= check("march mungmee: invoice_no", march["invoice_no"] == "INV-2568-03")
    all_ok &= check(
        "'/ Name' left over from a bilingual label is not a buyer name",
        extractor._is_plausible_buyer_name(extractor._clean_buyer_value(" / Name")) is False,
    )
    all_ok &= check(
        "'/ Customer Name' is not a buyer name either",
        extractor._is_plausible_buyer_name(extractor._clean_buyer_value(" / Customer Name")) is False,
    )
    all_ok &= check(
        "an English company name IS still a valid buyer",
        extractor._is_plausible_buyer_name(extractor._clean_buyer_value("ABC Co., Ltd.")),
    )

    # regression: the เอเชี่ยน โลจิสติกส์ invoice (see REAL_ASIAN_RAW_TEXT)
    fields13 = extractor.extract_fields(REAL_ASIAN_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real เอเชี่ยน โลจิสติกส์ OCR text fields ---")
    for k, v in fields13.items():
        print(f"  {k}: {v}")
    all_ok &= check("real asian: subtotal = 60500.0 (was the total)", fields13["subtotal"] == 60500.00)
    all_ok &= check("real asian: vat = 4235.0 (was missing)", fields13["vat"] == 4235.00)
    all_ok &= check("real asian: total = 64735.0 (was missing)", fields13["total"] == 64735.00)
    all_ok &= check("real asian: invoice_no", fields13["invoice_no"] == "INV-6802-0147")
    all_ok &= check("real asian: date = 2025-01-18", fields13["invoice_date_iso"] == "2025-01-18")
    all_ok &= check("real asian: buyer_name", fields13["buyer_name"] == "บริษัท C จำกัด")
    all_ok &= check("real asian: classified เต็มรูป", fields13["doc_type"] == "เต็มรูป")
    all_ok &= check("real asian: not flagged for review", fields13["needs_review"] is False)

    # damaged label text the extractor now has to survive
    all_ok &= check(
        "'รวมเงินทั้งสิ้น' is the grand total, not the subtotal",
        extractor._classify_totals_label("รวมเงินทั้งสิ้น") == "total",
    )
    all_ok &= check(
        "plain 'รวมเงิน' is still the subtotal",
        extractor._classify_totals_label("รวมเงิน 2,000.00") == "subtotal",
    )
    all_ok &= check(
        "'ษีมูลค่าเพิ่ม 7%' (clipped syllable) is still the VAT",
        extractor._classify_totals_label("ษีมูลค่าเพิ่ม 7%") == "vat",
    )
    all_ok &= check(
        "the clipped form still can't hijack the VATable-goods line",
        extractor._classify_totals_label("สินค้าที่เสียภาษีมูลค่าเพิ่ม") == "subtotal",
    )
    all_ok &= check(
        "the clipped form still can't hijack the exempt-goods line",
        extractor._classify_totals_label("สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม") == "exempt",
    )
    all_ok &= check(
        "'ทุกคาสินค้าบริการ' (mangled มูลค่าสินค้า/บริการ) is the subtotal",
        extractor._classify_totals_label("ทุกคาสินค้าบริการ") == "subtotal",
    )

    # regression: the ไทยสยาม เทรดดิ้ง invoice (see REAL_THAISIAM_RAW_TEXT)
    fields14 = extractor.extract_fields(REAL_THAISIAM_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real ไทยสยาม เทรดดิ้ง OCR text fields ---")
    for k, v in fields14.items():
        print(f"  {k}: {v}")
    all_ok &= check("real thaisiam: subtotal = 34350.0", fields14["subtotal"] == 34350.00)
    all_ok &= check("real thaisiam: vat = 2404.5 (was missing)", fields14["vat"] == 2404.50)
    all_ok &= check("real thaisiam: total = 36754.5 (was the subtotal)", fields14["total"] == 36754.50)
    all_ok &= check("real thaisiam: invoice_no", fields14["invoice_no"] == "TS-INV-016801")
    all_ok &= check("real thaisiam: date = 2025-01-22", fields14["invoice_date_iso"] == "2025-01-22")
    all_ok &= check("real thaisiam: buyer_name", fields14["buyer_name"] == "บริษัท C จำกัด")
    all_ok &= check("real thaisiam: not flagged for review", fields14["needs_review"] is False)

    # SARA AM doubled by a SARA AA — OCR does this constantly
    all_ok &= check(
        "'ยอดชำาระสุทธิ' normalises to 'ยอดชำระสุทธิ'",
        extractor.normalize_thai_text("ยอดชำาระสุทธิ") == "ยอดชำระสุทธิ",
    )
    all_ok &= check(
        "'วันครบกำาหนด' normalises to 'วันครบกำหนด'",
        extractor.normalize_thai_text("วันครบกำาหนด") == "วันครบกำหนด",
    )
    all_ok &= check(
        "'ยอดชำระสุทธิ' is the total",
        extractor._classify_totals_label(extractor.normalize_thai_text("ยอดชำาระสุทธิ")) == "total",
    )
    all_ok &= check(
        "'ภาพมูลค่าเพิ่ม 7%' (ษี misread as พ) is still the VAT",
        extractor._classify_totals_label("ภาพมูลค่าเพิ่ม 7%") == "vat",
    )
    all_ok &= check(
        "the loosened VAT pattern still can't claim the VATable-goods line",
        extractor._classify_totals_label("สินค้าที่เสียภาษีมูลค่าเพิ่ม") == "subtotal",
    )
    all_ok &= check(
        "the loosened VAT pattern still can't claim the exempt line",
        extractor._classify_totals_label("สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม") == "exempt",
    )
    all_ok &= check(
        "an amount-in-words line never supplies a figure",
        extractor._find_after_keyword(
            "จำนวนเงินรวมทั้งสิ้น (ตัวอักษร)\nรวมมูลค่าสินค้า\n35,350.00\n",
            extractor.TOTAL_KEYWORDS,
        ) is None,
    )

    # regression: JP invoice IV6800413-079, whose ONLY occurrence of the
    # words "ใบกำกับภาษี" came through as "ใบก๋ากับภาษี" (SARA AM read as MAI
    # CHATTAWA + SARA AA). With no tax-invoice marker the document was
    # classified ใบย่อ, and ม.86/6 then wiped its subtotal and VAT — both
    # of which had in fact been extracted correctly. One garbled letter
    # cost three fields and the VAT deduction.
    jp2 = extractor.extract_fields(
        REAL_JP_RAW_TEXT
        .replace("ใบกำกับภาษี/ใบเสร็จรับเงิน", "ใบก๋ากับภาษี/ใบเสร็จรับเงิน")
        .replace("IV6800413-039", "IV6800413-079"),
        ocr_confidence=92.0,
    )
    all_ok &= check("garbled marker: still เต็มรูป", jp2["doc_type"] == "เต็มรูป")
    all_ok &= check("garbled marker: subtotal survives", jp2["subtotal"] == 1300.0)
    all_ok &= check("garbled marker: vat survives", jp2["vat"] == 91.0)
    all_ok &= check("garbled marker: total", jp2["total"] == 1391.0)
    for spelling in ["ใบกำกับภาษี", "ใบก๋ากับภาษี", "ใบกํากับภาษี", "ใบกากับภาษี"]:
        all_ok &= check(
            f"'{spelling}' counts as a tax-invoice marker",
            bool(re.search(extractor.TAXINV_MARKER, spelling)),
        )
    all_ok &= check(
        "the English title alone counts as a marker",
        bool(re.search(extractor.TAXINV_MARKER, "TAX INVOICE / RECEIPT")),
    )
    # the loosened marker must not turn ordinary words into one, and the
    # per-keyword tolerance must not bleed into a blanket vowel rewrite —
    # "ค่า" is a real syllable that appears in almost every invoice
    all_ok &= check(
        "'ใบเสร็จรับเงิน' alone is still not a tax-invoice marker",
        re.search(extractor.TAXINV_MARKER, "ใบเสร็จรับเงิน") is None,
    )
    all_ok &= check(
        "'มูลค่า' is left alone by normalisation",
        extractor.normalize_thai_text("ราคา มูลค่าเพิ่ม ค่าบริการ") == "ราคา มูลค่าเพิ่ม ค่าบริการ",
    )

    # regression: the December มั่งมีศรีสุข invoice INV-2568-12, dated
    # 31/12/2568, which was filed as 2026-01-03 — a date lifted from the
    # holiday notice among the terms at the foot of the page ("...คำสั่งซื้อ
    # ดำเนินการต่ออีกครั้งวันที่ 3 มกราคม 2569"). The document box had the
    # right date paired with the invoice number all along; extract_fields
    # was only reading the number out of it.
    december = extractor.extract_fields(
        REAL_MUNGMEE_RAW_TEXT
        .replace("นามผู้ชื้อ / Name", "นามผู้ซื้อ / Name")
        .replace("INV-2568-01", "INV-2568-12")
        .replace("31/01/2568", "31/12/2568")
        + "- ปิดทำการวันหยุดปีใหม่ 30 ธันวาคม 2568 - 2 มกราคม 2569 "
          "คำสั่งซื้อดำเนินการต่ออีกครั้งวันที่ 3 มกราคม 2569\n",
        ocr_confidence=90.0,
    )
    all_ok &= check(
        "december mungmee: date = 2025-12-31 (not the holiday notice's date)",
        december["invoice_date_iso"] == "2025-12-31",
    )
    all_ok &= check("december mungmee: invoice_no", december["invoice_no"] == "INV-2568-12")
    all_ok &= check(
        "a date inside a sentence is not the document's date",
        extractor.extract_date(
            "- ปิดทำการวันหยุดปีใหม่ 30 ธันวาคม 2568 - 2 มกราคม 2569 "
            "คำสั่งซื้อดำเนินการต่ออีกครั้งวันที่ 3 มกราคม 2569\n"
        )[1] != "2026-01-03",
    )
    all_ok &= check(
        "a short 'วันที่ ...' field line still supplies the date",
        extractor.extract_date("วันที่ 31/12/2568\n") == ("31/12/2568", "2025-12-31"),
    )

    # regression: the อรุณเทสต์ invoice (see REAL_ARUN_RAW_TEXT)
    fields15 = extractor.extract_fields(REAL_ARUN_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real อรุณเทสต์ OCR text fields ---")
    for k, v in fields15.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real arun: a 12-digit taxpayer ID is reported, not dropped",
        fields15["seller_tax_id"] == "990000010014",
    )
    all_ok &= check(
        "real arun: classified เต็มรูป (was downgraded to ย่อ)",
        fields15["doc_type"] == "เต็มรูป",
    )
    all_ok &= check("real arun: subtotal survives", fields15["subtotal"] == 24750.50)
    all_ok &= check("real arun: vat survives", fields15["vat"] == 1732.54)
    all_ok &= check("real arun: total", fields15["total"] == 26483.04)
    all_ok &= check(
        "real arun: buyer is the customer, not the seller's logo line",
        fields15["buyer_name"] == "ลูกค้าตัวอย่าง",
    )
    all_ok &= check(
        "real arun: the short taxpayer ID is flagged for review",
        fields15["needs_review"] and "13 หลัก" in (fields15["review_reason"] or ""),
    )

    # a name that merely contains "ลูกค้า" is still a name
    all_ok &= check(
        "'ชื่อลูกค้า' is a bare label",
        extractor._is_bare_buyer_label("ชื่อลูกค้า"),
    )
    all_ok &= check(
        "'ลูกค้า / Customer' is a bare label",
        extractor._is_bare_buyer_label("ลูกค้า / Customer"),
    )
    all_ok &= check(
        "'รหัสลูกค้า / CUSTOMER' is a bare label",
        extractor._is_bare_buyer_label("รหัสลูกค้า / CUSTOMER"),
    )
    all_ok &= check(
        "'ลูกค้าตัวอย่าง' is a NAME, not a label",
        extractor._is_bare_buyer_label("ลูกค้าตัวอย่าง") is False,
    )
    all_ok &= check(
        "'สำนักงานใหญ่' alone does not make a company name",
        extractor.BUYER_ENTITY_HINT_RE.search("ARUN TEST สาขา สำนักงานใหญ่") is None,
    )
    all_ok &= check(
        "'บริษัท รจนา จำกัด (สำนักงานใหญ่)' still reads as a company",
        bool(extractor.BUYER_ENTITY_HINT_RE.search("บริษัท รจนา จำกัด (สำนักงานใหญ่)")),
    )
    all_ok &= check(
        "a 13-digit ID is still preferred over a labelled short one",
        extractor.extract_tax_id(
            "เลขประจำตัวผู้เสียภาษี 990000010014\nเลขประจำตัวผู้เสียภาษี 0105569123456\n"
        ) == "0105569123456",
    )

    # regression: the บลูไพน์ invoice (see REAL_BLUEPINE_RAW_TEXT)
    fields16 = extractor.extract_fields(REAL_BLUEPINE_RAW_TEXT, ocr_confidence=90.0)
    print("\n--- Real บลูไพน์ OCR text fields ---")
    for k, v in fields16.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real bluepine: 'ข้อมูลผู้ซื้อ / BUYER' finds the buyer",
        fields16["buyer_name"] == "บริษัท ตัวอย่าง เทคโนโลยี จำกัด",
    )
    all_ok &= check("real bluepine: classified เต็มรูป", fields16["doc_type"] == "เต็มรูป")
    all_ok &= check("real bluepine: subtotal survives", fields16["subtotal"] == 12990.25)
    all_ok &= check("real bluepine: vat survives", fields16["vat"] == 909.32)
    all_ok &= check("real bluepine: total", fields16["total"] == 13899.57)
    all_ok &= check("real bluepine: invoice_no", fields16["invoice_no"] == "INV-0002")
    all_ok &= check("real bluepine: date = 2026-05-14", fields16["invoice_date_iso"] == "2026-05-14")

    # buyer labels this now understands, and the prose it must still ignore
    all_ok &= check(
        "'ข้อมูลผู้ซื้อ / BUYER' is recognised as a bare label",
        extractor._is_bare_buyer_label("ข้อมูลผู้ซื้อ / BUYER"),
    )
    all_ok &= check(
        "the word ผู้ซื้อ inside the printed conditions is not a buyer label",
        extractor.extract_buyer_name(
            "ใบกำกับภาษี\n"
            "- สินค้าตามใบกำกับภาษีนี้ แม้จะส่งมอบแก่ผู้ซื้อแล้วก็ยังคงเป็นทรัพย์สินของผู้ขาย"
            "จนกว่าผู้ซื้อได้ชำระเงินเรียบร้อยแล้ว\n"
            "บริษัท ไม่เกี่ยวข้อง จำกัด\n"
        ) is None,
    )
    all_ok &= check(
        "'ข้อมูลผู้ขาย / SELLER' is not a buyer label",
        extractor._is_bare_buyer_label("ข้อมูลผู้ขาย / SELLER") is False,
    )

    # regression: the ไพรม์เวิร์ค invoice INV-0009, whose buyer came out as
    # "ชื่อลูกค้า : ลูกค้าตัวอย่าง" — the label glued to the value. The box
    # heading "ลูกค้า / Customer" sits on its own line above, so THAT is
    # what the keyword matched; the value was then read off the next line
    # with its own label still attached, and nothing stripped a leading
    # THAI label (only Latin ones were handled).
    primework = extractor.extract_fields(
        "P\nบริษัท ไพรม์เวิร์ค เทคโนโลยี จำกัด\nPRIMEWORK TECHNOLOGY CO., LTD.\n"
        "เลขประจำตัวผู้เสียภาษีอากร 990000010097\nPRIMEWORK สาขา 00001\n"
        "ใบกำกับภาษี\nTAX INVOICE\nเลขที่ใบกำกับภาษี\n(Invoice No.)\n: INV-0009\n"
        "วันที่ออกใบกำกับภาษี : 11/09/2026\n(Invoice Date)\n"
        "ลูกค้า / Customer\nชื่อลูกค้า : ลูกค้าตัวอย่าง\n"
        "ที่อยู่ : 123 ถนนตัวอย่าง ตำบลตัวอย่าง\nจังหวัดตัวอย่าง 50000\n"
        "มูลค่าสินค้า/บริการ (Subtotal)\n36,500.00\n"
        "ภาษีมูลค่าเพิ่ม 7% (VAT 7%)\n2,555.00\n"
        "จำนวนเงินรวมทั้งสิ้น (Total)\n39,055.00\n",
        ocr_confidence=90.0,
    )
    all_ok &= check(
        "primework: buyer is the name alone, without its label",
        primework["buyer_name"] == "ลูกค้าตัวอย่าง",
    )
    all_ok &= check("primework: subtotal", primework["subtotal"] == 36500.00)
    all_ok &= check("primework: vat", primework["vat"] == 2555.00)
    all_ok &= check("primework: total", primework["total"] == 39055.00)

    # stripping a leading Thai label needs its separator, so a name that
    # merely begins with one of those words survives intact
    for raw, want in [("ชื่อลูกค้า : ลูกค้าตัวอย่าง", "ลูกค้าตัวอย่าง"),
                      ("ชื่อลูกค้า/Customer Name : บริษัท เอ จำกัด", "บริษัท เอ จำกัด"),
                      ("นามผู้ซื้อ : บริษัท A จำกัด", "บริษัท A จำกัด"),
                      ("ลูกค้าตัวอย่าง", "ลูกค้าตัวอย่าง"),
                      ("บริษัท ลูกค้าดี จำกัด", "บริษัท ลูกค้าดี จำกัด")]:
        all_ok &= check(f"clean buyer value {raw!r} -> {want!r}",
                        extractor._clean_buyer_value(raw) == want)

    # regression: a second ฟาร์มเงินฟาร์มทอง invoice, INV-2568-004, where the
    # totals box lost to three separate problems at once:
    #   - OCR dropped the whole signature block INTO the label run, so the
    #     run broke in two and the box ended up with five labels against
    #     six figures — no exact-length pairing was possible.
    #   - "รวมเงิน" and its English twin "Total" classify differently
    #     (subtotal vs grand total), splitting one field into two labels.
    #   - "รวมราคาสินค้า" matched nothing (the keyword was the other word
    #     order, "ราคารวมสินค้า").
    # And the fallback keyword search then read "1" out of the numbered
    # conditions ("1. สินค้าตามใบส่งสินค้านี้...") because its window pass
    # didn't skip the items-table column headings the line pass skips.
    farm2 = extractor.extract_fields(
        "ต้นฉบับใบกำกับภาษี/ใบส่งสินค้า\nเลขที่\nNo.\nINV-2568-004\nวันที่\nDate\n30/04/2568\n"
        "ชื่อลูกค้า\nCustomer Name\nบริษัท ฟาร์มเงินฟาร์มทอง จำกัด\n"
        "FARM NGERN FARM THONG CO., LTD.\n"
        "เลขประจำตัวผู้เสียภาษีอากร 0173568002246 (สำนักงานใหญ่)\nบริษัท A จำกัด\n"
        "จำนวนเงิน\nAmount\n25,500.00\n120\n780.00\n93,600.00\n"
        "1. สินค้าตามใบส่งสินค้านี้ หากมีการแตกร้าวหรือชำรุดเสียหาย กรุณาแจ้งกลับภายใน 3 วัน\n"
        "รวมเงิน\nTotal\n"
        "ได้รับสินค้าตามรายการถูกต้องเรียบร้อยแล้ว\nReceived the above goods in good condition\n"
        "ผู้รับสินค้า .\nReceived by\nผู้ส่งสินค้า\nDelivery by\nวันที่ 30/04/2568\n"
        "หักเงินมัดจำ\nDeposit\nหักส่วนลด\nDiscount\nรวมราคาสินค้า\nSub Total\n"
        "ภาษีมูลค่าเพิ่ม\nVAT\nจำนวนเงินรวมทั้งสิ้น\nGrand Total\n"
        "ในนาม บริษัท ฟาร์มเงินฟาร์มทอง จำกัด\nผู้มีอำนาจลงนาม\nAuthorized Signature\n"
        "119,100.00\n0.00\n0.00\n119,100.00\n8,337.00\n127,437.00\n",
        ocr_confidence=90.0,
    )
    all_ok &= check("farm2: subtotal = 119100.0 (was 1)", farm2["subtotal"] == 119100.00)
    all_ok &= check("farm2: vat = 8337.0 (was missing)", farm2["vat"] == 8337.00)
    all_ok &= check("farm2: total = 127437.0 (was missing)", farm2["total"] == 127437.00)
    all_ok &= check("farm2: invoice_no", farm2["invoice_no"] == "INV-2568-004")
    all_ok &= check("farm2: not flagged for review", farm2["needs_review"] is False)

    all_ok &= check(
        "'รวมราคาสินค้า' is the subtotal (either word order)",
        extractor._classify_totals_label("รวมราคาสินค้า") == "subtotal",
    )
    all_ok &= check(
        "a bare English 'Total' is recognised as a label's translated twin",
        bool(extractor.GENERIC_TOTALS_WORD_RE.match("Total")),
    )
    all_ok &= check(
        "'จำนวนเงินรวมทั้งสิ้น' is not a generic English word",
        extractor.GENERIC_TOTALS_WORD_RE.match("จำนวนเงินรวมทั้งสิ้น") is None,
    )
    # a guessed alignment is only accepted when the amounts agree
    all_ok &= check(
        "an unsound alignment is rejected",
        extractor._totals_pairing_is_sound(
            {"subtotal": "100.00", "vat": "900.00", "total": "1,000.00"}
        ) is False,
    )
    all_ok &= check(
        "a sound alignment is accepted",
        extractor._totals_pairing_is_sound(
            {"subtotal": "119,100.00", "vat": "8,337.00", "total": "127,437.00"}
        ),
    )

    # regression: the พรเจริญ invoice (see REAL_PORNJAROEN_RAW_TEXT)
    fields17 = extractor.extract_fields(REAL_PORNJAROEN_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real พรเจริญ OCR text fields ---")
    for k, v in fields17.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real pornjaroen: invoice_no = INV-6808-015 (not the address '55/99')",
        fields17["invoice_no"] == "INV-6808-015",
    )
    all_ok &= check(
        "real pornjaroen: buyer is the customer, not the seller's tagline",
        fields17["buyer_name"] == "บริษัท เชียงใหม่ ดีไซน์ จำกัด",
    )
    all_ok &= check("real pornjaroen: date = 2025-08-18", fields17["invoice_date_iso"] == "2025-08-18")
    all_ok &= check("real pornjaroen: subtotal", fields17["subtotal"] == 127500.00)
    all_ok &= check("real pornjaroen: vat", fields17["vat"] == 8925.00)
    all_ok &= check("real pornjaroen: total", fields17["total"] == 136425.00)

    all_ok &= check(
        "'อุปกรณ์สำนักงาน' (office supplies) is not an entity name",
        extractor.BUYER_ENTITY_HINT_RE.search("อุปกรณ์สำนักงาน") is None,
    )
    all_ok &= check(
        "'สำนักงานบัญชี รุ่งเรือง' still is one",
        bool(extractor.BUYER_ENTITY_HINT_RE.search("สำนักงานบัญชี รุ่งเรือง")),
    )
    # a document box's pairing has to survive being scanned for
    all_ok &= check(
        "a taxpayer ID is not accepted as a document number",
        extractor._doc_info_pairing_is_sound({"doc_no": "0505567001234"}) is False,
    )
    all_ok &= check(
        "a date is not accepted as a document number",
        extractor._doc_info_pairing_is_sound({"doc_no": "13/04/68"}) is False,
    )
    all_ok &= check(
        "a real document number and date are accepted",
        extractor._doc_info_pairing_is_sound({"doc_no": "INV-6808-015", "doc_date": "18/08/2568"}),
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

    # regression: the three figures read correctly but paired with the
    # wrong labels. Reported from the live app twice — an invoice showed
    # VAT 511.00 and total 33.43 for 477.57 + 33.43 = 511.00. Every
    # rearrangement of a valid set must resolve to the one arrangement that
    # satisfies both relations.
    print("\n--- Swapped totals ---")
    for triple in [(477.57, 511.00, 33.43), (33.43, 477.57, 511.00),
                   (511.00, 33.43, 477.57), (33.43, 511.00, 477.57),
                   (511.00, 477.57, 33.43), (477.57, 33.43, 511.00)]:
        got = extractor.reconcile_totals(*triple)
        print(f"  {triple} -> {got}")
        all_ok &= check(f"swapped totals {triple} -> (477.57, 33.43, 511.0)",
                        got == (477.57, 33.43, 511.00))
    all_ok &= check(
        "figures that are simply wrong are NOT rearranged into a fake fit",
        extractor.reconcile_totals(100.0, 55.0, 900.0) == (100.0, 55.0, 900.0),
    )

    # yyyy/mm/dd dates, which used to be matched from their third character
    all_ok &= check("'2025/02/18' -> 2025-02-18", extractor._parse_thai_date("2025/02/18") == "2025-02-18")
    all_ok &= check("'2568/02/18' (พ.ศ.) -> 2025-02-18", extractor._parse_thai_date("2568/02/18") == "2025-02-18")
    all_ok &= check("'18/02/2025' still -> 2025-02-18", extractor._parse_thai_date("18/02/2025") == "2025-02-18")
    all_ok &= check("'14/07/68' still -> 2025-07-14", extractor._parse_thai_date("14/07/68") == "2025-07-14")
    all_ok &= check(
        "a yyyy/mm/dd date is captured whole, not from its third digit",
        extractor.extract_date("วันที่ 2025/02/18\n") == ("2025/02/18", "2025-02-18"),
    )

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

    # regression: the กรีนฟิลด์ invoice (see REAL_GREENFIELD_RAW_TEXT)
    fields18 = extractor.extract_fields(REAL_GREENFIELD_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real กรีนฟิลด์ OCR text fields ---")
    for k, v in fields18.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real greenfield: seller is the issuer, not the customer read above it",
        fields18["seller_name"] == "บริษัท กรีนฟิลด์ ออฟฟิศ ซัพพลาย จำกัด",
    )
    all_ok &= check(
        "real greenfield: buyer is the customer, not the issuer",
        fields18["buyer_name"] == "บริษัท สตาร์เทรดดิ้ง จำกัด",
    )
    all_ok &= check(
        "real greenfield: date = issue date 2026-09-15 (not due date 2026-10-15)",
        fields18["invoice_date_iso"] == "2026-09-15",
    )
    all_ok &= check("real greenfield: invoice_no", fields18["invoice_no"] == "GF-INV-2026-0098")
    all_ok &= check("real greenfield: tax id", fields18["seller_tax_id"] == "0105567012348")
    all_ok &= check("real greenfield: subtotal", fields18["subtotal"] == 5000.00)
    all_ok &= check("real greenfield: vat", fields18["vat"] == 350.00)
    all_ok &= check("real greenfield: total", fields18["total"] == 5350.00)
    all_ok &= check("real greenfield: doc_type", fields18["doc_type"] == "เต็มรูป")

    # the two halves of the fix, checked on their own
    all_ok &= check(
        "a name under 'ลูกค้า / Customer' is not the seller",
        extractor._under_buyer_label(
            ["ลูกค้า / Customer", "บริษัท สตาร์เทรดดิ้ง จำกัด"], 1
        ),
    )
    all_ok &= check(
        "a name under an address line still is",
        extractor._under_buyer_label(["99/1 ถนนตัวอย่าง", "บริษัท ข จำกัด"], 1) is False,
    )
    all_ok &= check(
        "a due-date label is not the document's date",
        extractor._is_other_field_date(
            "วันที่ครบกำหนดชำระ", re.search("วันที่", "วันที่ครบกำหนดชำระ")
        ),
    )
    all_ok &= check(
        "'Due Date' is not either",
        extractor._is_other_field_date("Due Date", re.search("Date", "Due Date")),
    )
    all_ok &= check(
        "the issue-date label still is",
        extractor._is_other_field_date(
            "วันที่ออกใบกำกับภาษี", re.search("วันที่", "วันที่ออกใบกำกับภาษี")
        ) is False,
    )

    # regression: the บลูมูน invoice (see REAL_BLUEMOON_RAW_TEXT)
    fields19 = extractor.extract_fields(REAL_BLUEMOON_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real บลูมูน OCR text fields ---")
    for k, v in fields19.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real bluemoon: seller is the registered name, not the logo wordmark",
        fields19["seller_name"] == "บริษัท บลูมูน เทรดดิ้ง จำกัด",
    )
    all_ok &= check(
        "real bluemoon: tax id is the seller's spaced-out one, not the buyer's",
        fields19["seller_tax_id"] == "0505512345678",
    )
    all_ok &= check("real bluemoon: buyer", fields19["buyer_name"] == "บริษัท เชียงใหม่กูร์เม่ต์ จำกัด")
    all_ok &= check("real bluemoon: invoice_no", fields19["invoice_no"] == "BM-2026081507")
    all_ok &= check("real bluemoon: date", fields19["invoice_date_iso"] == "2025-08-15")
    all_ok &= check("real bluemoon: subtotal", fields19["subtotal"] == 59000.00)
    all_ok &= check("real bluemoon: vat", fields19["vat"] == 4130.00)
    all_ok &= check("real bluemoon: total", fields19["total"] == 63130.00)
    all_ok &= check("real bluemoon: doc_type", fields19["doc_type"] == "เต็มรูป")

    # the two halves of the fix, checked on their own
    all_ok &= check(
        "a letter-spaced taxpayer ID is read whole",
        extractor.extract_tax_id("เลขประจำตัวผู้เสียภาษีอากร 0 5 0 5512345678")
        == "0505512345678",
    )
    all_ok &= check(
        "a labelled ID beats a loose 13-digit number printed earlier",
        extractor.extract_tax_id(
            "อ้างอิง 1234567890123\nเลขประจำตัวผู้เสียภาษี 0505512345678"
        ) == "0505512345678",
    )
    all_ok &= check(
        "a name broken in two is put back together, whatever the order",
        extractor._merge_split_company_name(["เทรดดิ้ง จำกัด", "บริษัท บลูมูน"], 1)
        == "บริษัท บลูมูน เทรดดิ้ง จำกัด",
    )
    all_ok &= check(
        "a complete name is left alone",
        extractor._merge_split_company_name(
            ["บริษัท รจนา จำกัด", "99/1 ถนนตัวอย่าง"], 0
        ) == "บริษัท รจนา จำกัด",
    )

    # regression: the กรีนฟิลด์ ซัพพลาย invoice (see
    # REAL_GREENFIELD_SUPPLY_RAW_TEXT)
    fields20 = extractor.extract_fields(REAL_GREENFIELD_SUPPLY_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real กรีนฟิลด์ ซัพพลาย OCR text fields ---")
    for k, v in fields20.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real greenfield supply: tax id is the issuer's, not the customer's",
        fields20["seller_tax_id"] == "0505512345678",
    )
    all_ok &= check(
        "real greenfield supply: seller",
        fields20["seller_name"] == "บริษัท กรีนฟิลด์ ซัพพลาย จำกัด",
    )
    all_ok &= check(
        "real greenfield supply: buyer",
        fields20["buyer_name"] == "บริษัท เชียงใหม่ เบเกอรี่ แอนด์ คาเฟ่ จำกัด",
    )
    all_ok &= check("real greenfield supply: invoice_no", fields20["invoice_no"] == "GF-2026081501")
    all_ok &= check("real greenfield supply: date", fields20["invoice_date_iso"] == "2025-08-15")
    all_ok &= check("real greenfield supply: subtotal", fields20["subtotal"] == 27350.00)
    all_ok &= check("real greenfield supply: vat", fields20["vat"] == 1914.50)
    all_ok &= check("real greenfield supply: total", fields20["total"] == 29264.50)
    all_ok &= check("real greenfield supply: doc_type", fields20["doc_type"] == "เต็มรูป")

    # the two halves of the fix, checked on their own
    all_ok &= check(
        "a taxpayer-ID label survives OCR dropping a syllable",
        extractor.extract_tax_id("เลขประจำตัวผู้เสียกษีอากร 0 5 0 5 5 1 2 3 4 5 6 7 8")
        == "0505512345678",
    )
    all_ok &= check(
        "the ID inside the customer box loses to the issuer's",
        extractor.extract_tax_id(
            "บริษัท ผู้ขาย จำกัด\nเลขประจำตัวผู้เสียภาษี 0505512345678\n"
            "ชื่อผู้ซื้อ : บริษัท ผู้ซื้อ จำกัด\nเลขประจำตัวผู้เสียภาษี 0994000123456\n"
        ) == "0505512345678",
    )
    all_ok &= check(
        "...even when the customer box is read out first",
        extractor.extract_tax_id(
            "ชื่อผู้ซื้อ : บริษัท ผู้ซื้อ จำกัด\nเลขประจำตัวผู้เสียภาษี 0994000123456\n"
            "บริษัท ผู้ขาย จำกัด\nเลขประจำตัวผู้เสียภาษี 0505512345678\n"
        ) == "0505512345678",
    )

    # regression: the โคราชเทค invoice (see REAL_KORATTECH_RAW_TEXT)
    fields21 = extractor.extract_fields(REAL_KORATTECH_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real โคราชเทค OCR text fields ---")
    for k, v in fields21.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real korattech: subtotal is the figure after discount, not an item number",
        fields21["subtotal"] == 12230.00,
    )
    all_ok &= check("real korattech: vat (not the postcode 30000)", fields21["vat"] == 856.10)
    all_ok &= check("real korattech: total", fields21["total"] == 13086.10)
    all_ok &= check("real korattech: the three amounts agree", fields21["needs_review"] is False)
    all_ok &= check("real korattech: invoice_no", fields21["invoice_no"] == "INV-6809045")
    all_ok &= check("real korattech: date", fields21["invoice_date_iso"] == "2025-09-09")
    all_ok &= check("real korattech: buyer", fields21["buyer_name"] == "บริษัท เอสพี เคมิคอล จำกัด")
    all_ok &= check("real korattech: tax id", fields21["seller_tax_id"] == "0105569018274")

    # the arithmetic scan, checked on its own
    all_ok &= check(
        "the one balanced triple in a run of figures is found",
        extractor._balanced_triple([12430.0, 200.0, 12230.0, 856.10, 13086.10])
        == (12230.0, 856.10, 13086.10),
    )
    all_ok &= check(
        "a run that balances two different ways is rejected as ambiguous",
        extractor._balanced_triple(
            [100.0, 7.0, 107.0, 200.0, 14.0, 214.0]
        ) is None,
    )
    all_ok &= check(
        "a run where nothing balances yields nothing",
        extractor._balanced_triple([1.0, 30000.0, 5.0, 450.0]) is None,
    )
    # the guard: a figure read from its own label is never second-guessed,
    # so an invoice whose printed amounts really do disagree stays flagged
    mismatched = extractor.extract_fields(
        "บริษัท ทดสอบ จำกัด\nเลขประจำตัวผู้เสียภาษี 0105567123469\n"
        "ใบกำกับภาษี\nชื่อลูกค้า : บริษัท เอ จำกัด\n"
        "เลขที่ใบกำกับภาษี IV6800107-054\nวันที่ 07/01/68\n"
        "ราคารวมสินค้า (บาท) 1,900.00\nภาษีมูลค่าเพิ่ม (VAT) 7% 140.00\n"
        "รวมทั้งสิ้น 2,040.00\n",
        ocr_confidence=92.0,
    )
    all_ok &= check(
        "printed amounts that disagree are still flagged, not rewritten",
        mismatched["needs_review"] is True and mismatched["vat"] == 140.00,
    )

    # regression: the ขอนแก่น โปรออฟฟิศ invoice (see REAL_KHONKAEN_RAW_TEXT)
    fields22 = extractor.extract_fields(REAL_KHONKAEN_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real ขอนแก่น โปรออฟฟิศ OCR text fields ---")
    for k, v in fields22.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real khonkaen: seller name drops the parenthesis OCR never closed",
        fields22["seller_name"] == "บริษัท ขอนแก่น โปรออฟฟิศ ซัพพลาย จำกัด",
    )
    all_ok &= check(
        "real khonkaen: tax id is the issuer's, not the buyer's",
        fields22["seller_tax_id"] == "0105568123476",
    )
    all_ok &= check(
        "real khonkaen: invoice_no is the number, not the table heading 'ITEM'",
        fields22["invoice_no"] == "INV-6809-042",
    )
    all_ok &= check(
        "real khonkaen: buyer name has its mangled label stripped",
        fields22["buyer_name"] == "บริษัท อิสาน พัฒนาการค้า จำกัด (สำนักงานใหญ่)",
    )
    all_ok &= check("real khonkaen: date", fields22["invoice_date_iso"] == "2025-09-18")
    all_ok &= check("real khonkaen: subtotal", fields22["subtotal"] == 8737.55)
    all_ok &= check("real khonkaen: vat", fields22["vat"] == 611.65)
    all_ok &= check("real khonkaen: total", fields22["total"] == 9349.50)
    all_ok &= check("real khonkaen: doc_type", fields22["doc_type"] == "เต็มรูป")

    # the four fixes, checked on their own
    all_ok &= check(
        "an unclosed parenthesis is trimmed",
        extractor._trim_unclosed_paren("บริษัท ก จำกัด (สานักงาน") == "บริษัท ก จำกัด",
    )
    all_ok &= check(
        "a closed one is kept",
        extractor._trim_unclosed_paren("บริษัท ก จำกัด (สำนักงานใหญ่)")
        == "บริษัท ก จำกัด (สำนักงานใหญ่)",
    )
    all_ok &= check(
        "a copy designation is not a customer box",
        extractor._in_buyer_block(
            ["ต้นฉบับสำหรับลูกค้า / Original", "เลขประจำตัวผู้เสียภาษี 0105568123476"], 1
        ) is False,
    )
    all_ok &= check(
        "a real customer box still is",
        extractor._in_buyer_block(
            ["ชื่อผู้ซื้อ : บริษัท ก จำกัด", "เลขประจำตัวผู้เสียภาษี 0105568123476"], 1
        ),
    )
    all_ok &= check(
        "a word with no digit is not a document number",
        extractor._doc_info_pairing_is_sound({"doc_no": "ITEM"}) is False,
    )
    all_ok &= check(
        "an unrecognisable label in front of a separator is still stripped",
        extractor._clean_buyer_value("นามสื่อ / Name : บริษัท อิสาน พัฒนาการค้า จำกัด")
        == "บริษัท อิสาน พัฒนาการค้า จำกัด",
    )

    # regression: the บลูมมิ่ง ไลฟ์ invoice (see REAL_BLOOMING_RAW_TEXT)
    fields23 = extractor.extract_fields(REAL_BLOOMING_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real บลูมมิ่ง ไลฟ์ OCR text fields ---")
    for k, v in fields23.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real blooming: buyer found although the page labels nobody",
        fields23["buyer_name"] == "บริษัท B จำกัด",
    )
    all_ok &= check(
        "real blooming: a full tax invoice, not ย่อ",
        fields23["doc_type"] == "เต็มรูป",
    )
    all_ok &= check("real blooming: subtotal survives ม.86/6", fields23["subtotal"] == 883.18)
    all_ok &= check("real blooming: vat survives ม.86/6", fields23["vat"] == 61.82)
    all_ok &= check("real blooming: total", fields23["total"] == 945.00)
    all_ok &= check("real blooming: seller", fields23["seller_name"] == "บริษัท บลูมมิ่ง ไลฟ์ จำกัด")
    all_ok &= check("real blooming: tax id", fields23["seller_tax_id"] == "0134563248907")
    all_ok &= check("real blooming: invoice_no", fields23["invoice_no"] == "Inv001-57")
    all_ok &= check("real blooming: date", fields23["invoice_date_iso"] == "2025-01-07")
    all_ok &= check("real blooming: nothing left to review", fields23["needs_review"] is False)

    # the positional fallback, checked on its own
    all_ok &= check(
        "the seller's own bank block is not mistaken for the buyer",
        extractor._buyer_by_position(
            ["บริษัท ผู้ขาย จำกัด", "ชื่อบัญชี บริษัท ผู้ขาย จำกัด", "ธนาคาร ABC"],
            "บริษัท ผู้ขาย จำกัด", {0},
        ) is None,
    )
    all_ok &= check(
        "the signature's 'ในนาม <company>' is not either",
        extractor._buyer_by_position(
            ["บริษัท ผู้ขาย จำกัด", "ในนาม บริษัท ผู้ขาย จำกัด", "ผู้มีอำนาจลงนาม"],
            "บริษัท ผู้ขาย จำกัด", {0},
        ) is None,
    )
    all_ok &= check(
        "a receipt naming only one party gains no invented buyer",
        extractor.extract_fields(ABBREVIATED_RECEIPT_TEXT, ocr_confidence=80.0)["buyer_name"]
        is None,
    )

    # regression: the บลูมแอนด์โค invoice (see REAL_BLOOMANDCO_RAW_TEXT)
    fields24 = extractor.extract_fields(REAL_BLOOMANDCO_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real บลูมแอนด์โค OCR text fields ---")
    for k, v in fields24.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real bloomandco: invoice_no read from above its label, not the buyer's house number",
        fields24["invoice_no"] == "INV-2026-091",
    )
    all_ok &= check(
        "real bloomandco: buyer is the name, not the label 'ชื่อบริษัท'",
        fields24["buyer_name"] == "บริษัท เวลเนส พลัส จำกัด",
    )
    all_ok &= check(
        "real bloomandco: seller",
        fields24["seller_name"] == "บริษัท บลูมแอนด์โค ไลฟ์สไตล์ จำกัด",
    )
    all_ok &= check("real bloomandco: tax id", fields24["seller_tax_id"] == "0105567004321")
    all_ok &= check("real bloomandco: date", fields24["invoice_date_iso"] == "2026-09-05")
    all_ok &= check("real bloomandco: subtotal", fields24["subtotal"] == 18100.00)
    all_ok &= check("real bloomandco: vat", fields24["vat"] == 1267.00)
    all_ok &= check("real bloomandco: total", fields24["total"] == 19367.00)
    all_ok &= check("real bloomandco: doc_type", fields24["doc_type"] == "เต็มรูป")

    # the two fixes, checked on their own
    all_ok &= check(
        "a house number is not a document number",
        extractor._looks_like_doc_no("789") is False,
    )
    all_ok &= check(
        "a page marker is not either",
        extractor._looks_like_doc_no("1/1") is False,
    )
    all_ok &= check(
        "a date is not either",
        extractor._looks_like_doc_no("05/09/2569") is False,
    )
    all_ok &= check(
        "a real document number is",
        extractor._looks_like_doc_no("INV-2026-091"),
    )
    all_ok &= check(
        "'ชื่อบริษัท' is a label, not a buyer's name",
        extractor._is_bare_buyer_label("ชื่อบริษัท"),
    )
    all_ok &= check(
        "a company actually named that way is not a label",
        extractor._is_bare_buyer_label("บริษัท เวลเนส พลัส จำกัด") is False,
    )

    # regression: the สิงโต invoice (see REAL_SINGTO_RAW_TEXT)
    fields25 = extractor.extract_fields(REAL_SINGTO_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real สิงโต OCR text fields ---")
    for k, v in fields25.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real singto: subtotal read from the 'ราคารวม' line",
        fields25["subtotal"] == 60000.00,
    )
    all_ok &= check("real singto: vat", fields25["vat"] == 4200.00)
    all_ok &= check(
        "real singto: total is the grand total, not the VAT figure below its label",
        fields25["total"] == 64200.00,
    )
    all_ok &= check("real singto: the three amounts agree", fields25["needs_review"] is False)
    all_ok &= check("real singto: invoice_no", fields25["invoice_no"] == "77890")
    all_ok &= check("real singto: date", fields25["invoice_date_iso"] == "2025-08-25")
    all_ok &= check("real singto: buyer", fields25["buyer_name"] == "บริษัท กากา จำกัด")
    all_ok &= check("real singto: tax id", fields25["seller_tax_id"] == "0105562123454")
    all_ok &= check("real singto: doc_type", fields25["doc_type"] == "เต็มรูป")

    # the keyword and its guards, checked on their own
    all_ok &= check(
        "'ราคารวม' is the pre-VAT subtotal",
        extractor._classify_totals_label("ราคารวม") == "subtotal",
    )
    all_ok &= check(
        "'ราคารวมทั้งสิ้น' is still the grand total",
        extractor._classify_totals_label("ราคารวมทั้งสิ้น") == "total",
    )
    all_ok &= check(
        "the items table's own 'ราคารวม' heading is recognised as a heading",
        extractor._is_table_column_header(
            ["จำนวน", "ราคา/หน่วย", "ราคารวม", "1"], 2
        ),
    )
    all_ok &= check(
        "a totals line of the same name is not a heading",
        extractor._is_table_column_header(
            ["หมายเหตุ", "ราคารวม", "60,000"], 1
        ) is False,
    )

    # regression: the แบร์ เกียร์ invoice (see REAL_BEARGEAR_RAW_TEXT)
    fields26 = extractor.extract_fields(REAL_BEARGEAR_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real แบร์ เกียร์ OCR text fields ---")
    for k, v in fields26.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real beargear: invoice_no is the number, not the buyer's house number",
        fields26["invoice_no"] == "01210",
    )
    all_ok &= check(
        "real beargear: date read 16 lines from its label",
        fields26["invoice_date_iso"] == "2025-03-01",
    )
    all_ok &= check(
        "real beargear: buyer name loses the English half of its label",
        fields26["buyer_name"] == "บริษัท C จำกัด",
    )
    all_ok &= check(
        "real beargear: seller",
        fields26["seller_name"] == "บริษัท แบร์ เกียร์ ไอที ซิสเต็ม จำกัด",
    )
    all_ok &= check("real beargear: tax id", fields26["seller_tax_id"] == "0105568034567")
    all_ok &= check("real beargear: subtotal", fields26["subtotal"] == 7000.00)
    all_ok &= check("real beargear: vat", fields26["vat"] == 490.00)
    all_ok &= check("real beargear: total", fields26["total"] == 7490.00)
    all_ok &= check("real beargear: doc_type", fields26["doc_type"] == "เต็มรูป")

    # the three fixes, checked on their own
    all_ok &= check(
        "'เลขที่/ Invoice No' is a document-number label",
        extractor._classify_doc_info_label("เลขที่/ Invoice No") == "doc_no",
    )
    all_ok &= check(
        "a spelled-out Thai date is a document-box value",
        extractor._is_doc_value_line("1 มีนาคม 2568"),
    )
    all_ok &= check(
        "scattered labels pair with their value run by order",
        extractor._doc_info_by_order(
            ["เลขที่/ Invoice No", "ที่อยู่ / Address", "456/89 ถนนสุขุมวิท",
             "วันที่ / Date", "ครบกำหนด / Due Date",
             "01210", "1 มีนาคม 2568", "1 เมษายน 2568"]
        ) == {"doc_no": "01210", "doc_date": "1 มีนาคม 2568", "due_date": "1 เมษายน 2568"},
    )
    all_ok &= check(
        "an items-table fragment is not paired with them",
        extractor._doc_info_by_order(
            ["เลขที่/ Invoice No", "วันที่ / Date", "1", "2"]
        ) == {},
    )
    all_ok &= check(
        "an English label word with no punctuation is stripped",
        extractor._clean_buyer_value("Customer บริษัท C จำกัด") == "บริษัท C จำกัด",
    )

    # regression: the second แบร์ เกียร์ invoice (see REAL_BEARGEAR2_RAW_TEXT)
    fields27 = extractor.extract_fields(REAL_BEARGEAR2_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real แบร์ เกียร์ #2 OCR text fields ---")
    for k, v in fields27.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real beargear2: date read from a value run of spelled-out Thai dates",
        fields27["invoice_date_iso"] == "2025-02-01",
    )
    all_ok &= check("real beargear2: invoice_no", fields27["invoice_no"] == "01210")
    all_ok &= check("real beargear2: buyer", fields27["buyer_name"] == "บริษัท C จำกัด")
    all_ok &= check("real beargear2: tax id", fields27["seller_tax_id"] == "0105568034567")
    all_ok &= check("real beargear2: subtotal", fields27["subtotal"] == 6000.00)
    all_ok &= check("real beargear2: vat", fields27["vat"] == 420.00)
    all_ok &= check("real beargear2: total", fields27["total"] == 6420.00)
    all_ok &= check("real beargear2: doc_type", fields27["doc_type"] == "เต็มรูป")
    all_ok &= check("real beargear2: nothing left to review", fields27["needs_review"] is False)

    # the block extractor and the by-order fallback agree on what a value is
    all_ok &= check(
        "a run of labels keeps its spelled-out Thai dates",
        extractor._extract_doc_info_block(
            "เลขที่/ Invoice No\nวันที่ / Date\nครบกำหนด / Due Date\n"
            "01210\n1 กุมภาพันธ์ 2568\n1 มีนาคม 2568\n"
        ) == {"doc_no": "01210", "doc_date": "1 กุมภาพันธ์ 2568",
              "due_date": "1 มีนาคม 2568"},
    )

    # regression: a second scan of the สิงโต invoice (see REAL_SINGTO2_RAW_TEXT)
    fields28 = extractor.extract_fields(REAL_SINGTO2_RAW_TEXT, ocr_confidence=90.0)
    all_ok &= check(
        "real singto2: date with spaces around its slashes",
        fields28["invoice_date_iso"] == "2025-08-25",
    )
    all_ok &= check("real singto2: invoice_no", fields28["invoice_no"] == "77890")
    all_ok &= check("real singto2: subtotal", fields28["subtotal"] == 60000.00)
    all_ok &= check("real singto2: total", fields28["total"] == 64200.00)
    all_ok &= check(
        "'25 /08/ 2025' parses",
        extractor._parse_thai_date("25 /08/ 2025") == "2025-08-25",
    )
    all_ok &= check(
        "the spaces may not span a line break",
        extractor.DATE_TOKEN_RE.search("1\n/\n2\n/\n2025") is None,
    )

    # regression: the third JP invoice (see REAL_JP3_RAW_TEXT)
    fields29 = extractor.extract_fields(REAL_JP3_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real JP #3 OCR text fields ---")
    for k, v in fields29.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real jp3: invoice_no is the number, not an item row's unit price",
        fields29["invoice_no"] == "IV6801224-125",
    )
    all_ok &= check("real jp3: date", fields29["invoice_date_iso"] == "2025-12-24")
    all_ok &= check("real jp3: buyer", fields29["buyer_name"] == "บริษัท เอ จำกัด")
    all_ok &= check("real jp3: tax id", fields29["seller_tax_id"] == "0105576890143")
    all_ok &= check("real jp3: subtotal", fields29["subtotal"] == 2000.00)
    all_ok &= check("real jp3: vat", fields29["vat"] == 140.00)
    all_ok &= check("real jp3: total", fields29["total"] == 2140.00)
    all_ok &= check("real jp3: doc_type", fields29["doc_type"] == "เต็มรูป")
    all_ok &= check(
        "a document box does not pair with rows below the items-table heading",
        extractor._extract_doc_info_block(
            "พนักงานขาย/Salesman\nกำหนดชาระ/Due Date\nเลขที่/No.\n"
            "ล่าดับ\nรายการ\nจำนวน\n1.\nสีน้ำ\n6\n10\n130.-\n"
        ) == {},
    )

    # regression: the มั่งมีศรีสุข March invoice (see REAL_MUNGMEE_MAR_RAW_TEXT)
    fields30 = extractor.extract_fields(REAL_MUNGMEE_MAR_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real มั่งมีศรีสุข (มี.ค.) OCR text fields ---")
    for k, v in fields30.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real mungmee mar: subtotal is the VATable goods, not the exempt 0.00",
        fields30["subtotal"] == 5500.00,
    )
    all_ok &= check("real mungmee mar: vat", fields30["vat"] == 385.00)
    all_ok &= check("real mungmee mar: total", fields30["total"] == 5885.00)
    all_ok &= check(
        "real mungmee mar: the three amounts agree",
        fields30["needs_review"] is False,
    )
    all_ok &= check("real mungmee mar: invoice_no", fields30["invoice_no"] == "INV-2568-03")
    all_ok &= check("real mungmee mar: date", fields30["invoice_date_iso"] == "2025-03-31")
    all_ok &= check("real mungmee mar: buyer", fields30["buyer_name"] == "บริษัท A จำกัด")
    all_ok &= check("real mungmee mar: tax id", fields30["seller_tax_id"] == "0105568000222")

    # the two halves of the fix, checked on their own
    all_ok &= check(
        "more labels than figures pairs from the front",
        extractor._extract_totals_block(
            "สินค้าที่ยกเว้นภาษีมูลค่าเพิ่ม\nสินค้าที่เสียภาษีมูลค่าเพิ่ม\n"
            "ภาษีมูลค่าเพิ่ม VAT 7%\nหัก เงินมัดจำ\n0.00\n5,500.00\n385.00\n"
        ) == {"exempt": "0.00", "subtotal": "5,500.00", "vat": "385.00"},
    )
    all_ok &= check(
        "a pairing with no total is sound when the rate is exactly 7%",
        extractor._totals_pairing_is_sound({"subtotal": "5,500.00", "vat": "385.00"}),
    )
    all_ok &= check(
        "...and is not when it isn't",
        extractor._totals_pairing_is_sound({"subtotal": "0.00", "vat": "5,500.00"})
        is False,
    )

    # regression: the พรีเมียร์ คลีน invoice (see REAL_PREMIERCLEAN_RAW_TEXT)
    fields31 = extractor.extract_fields(REAL_PREMIERCLEAN_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real พรีเมียร์ คลีน OCR text fields ---")
    for k, v in fields31.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real premierclean: tax id is the issuer's, not the customer's above it",
        fields31["seller_tax_id"] == "0115569000012",
    )
    all_ok &= check(
        "real premierclean: seller",
        fields31["seller_name"] == "บริษัท พรีเมียร์ คลีน เซอร์วิส จำกัด",
    )
    all_ok &= check("real premierclean: buyer", fields31["buyer_name"] == "บริษัท B จำกัด")
    all_ok &= check("real premierclean: invoice_no", fields31["invoice_no"] == "000125")
    all_ok &= check("real premierclean: date", fields31["invoice_date_iso"] == "2025-01-31")
    all_ok &= check("real premierclean: subtotal", fields31["subtotal"] == 1800.00)
    all_ok &= check("real premierclean: vat", fields31["vat"] == 126.00)
    all_ok &= check("real premierclean: total", fields31["total"] == 1926.00)
    all_ok &= check("real premierclean: doc_type", fields31["doc_type"] == "เต็มรูป")

    # the customer box's extent, checked on its own
    customer_box = [
        "รายละเอียดลูกค้า", "บริษัท B จำกัด", "188 หมู่ 7 ถนนเชียงใหม่-ลำพูน",
        "จังหวัดเชียงใหม่ 50140", "เลขประจำตัวผู้เสียภาษี 0505569234567",
        "บริษัท พรีเมียร์ คลีน เซอร์วิส จำกัด", "โทร 087-5693687",
        "เลขประจำตัวผู้เสียภาษี 0115569000012",
    ]
    all_ok &= check(
        "the buyer's own name does not close the customer box",
        extractor._in_buyer_block(customer_box, 4),
    )
    all_ok &= check(
        "the next party's name does",
        extractor._in_buyer_block(customer_box, 7) is False,
    )

    # regression: a Makro POS receipt (see REAL_MAKRO_RAW_TEXT)
    fields32 = extractor.extract_fields(REAL_MAKRO_RAW_TEXT, ocr_confidence=90.0)
    print()
    print("--- Real Makro OCR text fields ---")
    for k, v in fields32.items():
        print(f"  {k}: {v}")
    all_ok &= check(
        "real makro: subtotal is the pre-VAT figure, not an item's price",
        fields32["subtotal"] == 332.71,
    )
    all_ok &= check("real makro: vat (not the quantity 1)", fields32["vat"] == 23.29)
    all_ok &= check("real makro: total", fields32["total"] == 356.00)
    all_ok &= check("real makro: the three amounts agree", fields32["needs_review"] is False)
    all_ok &= check(
        "real makro: invoice_no is this receipt's, not the cancelled one it replaces",
        fields32["invoice_no"] == "041501408013",
    )
    all_ok &= check("real makro: date", fields32["invoice_date_iso"] == "2025-07-22")
    all_ok &= check("real makro: tax id", fields32["seller_tax_id"] == "0107567000414")
    all_ok &= check(
        "real makro: seller",
        fields32["seller_name"] == "บริษัท ซีพี เอ็กซ์ตร้า จำกัด (มหาชน)",
    )

    # the three fixes, checked on their own
    all_ok &= check(
        "the number of a cancelled document is not this document's",
        extractor.extract_invoice_no(
            "เป็นการยกเลิกและออกใบกำกับภาษีฉบับใหม่ แทนฉบับเดิมเลขที่ 041030406649\n"
        ) != "041030406649",
    )
    all_ok &= check(
        "a 12-digit POS receipt number is a valid document number",
        extractor._doc_info_pairing_is_sound({"doc_no": "041501408013"}),
    )
    all_ok &= check(
        "a 13-digit taxpayer ID still is not",
        extractor._doc_info_pairing_is_sound({"doc_no": "0505567001234"}) is False,
    )
    all_ok &= check(
        "'เลขที่ใบเสร็จ' is a document-number label",
        extractor._classify_doc_info_label("เลขที่ใบเสร็จ") == "doc_no",
    )
    # the guard that keeps the arithmetic scan honest: a page whose printed
    # amounts genuinely disagree offers no balanced triple, so it stays flagged
    all_ok &= check(
        "printed amounts that disagree are STILL flagged, not rewritten",
        extractor.extract_fields(
            "บริษัท ทดสอบ จำกัด\nเลขประจำตัวผู้เสียภาษี 0105567123469\n"
            "ใบกำกับภาษี\nชื่อลูกค้า : บริษัท เอ จำกัด\n"
            "เลขที่ใบกำกับภาษี IV6800107-054\nวันที่ 07/01/68\n"
            "ราคารวมสินค้า (บาท) 1,900.00\nภาษีมูลค่าเพิ่ม (VAT) 7% 140.00\n"
            "รวมทั้งสิ้น 2,040.00\n", ocr_confidence=92.0,
        )["needs_review"] is True,
    )

    # ---- เลขยาว ๆ บนกระดาษไม่ใช่จำนวนเงิน ----
    # ยืนยันจากหน้าเว็บจริง: ใบ B2S หน้า 58 แสดง "ยอดรวม" เป็น
    # 6.62025072250051e+23 ซึ่งคือเลขใต้บาร์โค้ด 66202507225005110311586
    all_ok &= check(
        "a barcode number is not an amount",
        extractor._clean_number("66202507225005110311586") is None,
    )
    all_ok &= check(
        "a 13-digit taxpayer ID is not an amount either",
        extractor._clean_number("0994000423179") is None,
    )
    all_ok &= check(
        "a 12-digit POS receipt number is not an amount",
        extractor._clean_number("041501408013") is None,
    )
    # ...แต่จำนวนเงินจริงต้องไม่โดนลูกหลง รวมถึงใบที่ยอดหลักล้าน
    all_ok &= check(
        "an ordinary amount still parses",
        extractor._clean_number("1,107.50") == 1107.50,
    )
    all_ok &= check(
        "a million-baht amount still parses",
        extractor._clean_number("9,876,543.21") == 9876543.21,
    )

    # ---- ประโยค "ยกเลิกใบเดิม" ต้องไม่ถูกขุดเอาเลขที่/วันที่ ----
    # ประโยคด้านล่างคัดมาจากใบจริง B2S หน้า 58 ของกอง "ใบจริงอันใหม่.pdf"
    # ใบนี้ออกแทนใบย่อที่ถูกยกเลิก จึงประกาศเลขที่และวันที่ของใบเก่าไว้ใต้
    # หัวเรื่อง. Makro เขียนว่า "แทนฉบับเดิมเลขที่ ..." ซึ่งการ์ดเดิมจับได้
    # ด้วย lookbehind "เดิม" แต่ B2S เขียนว่า "ยกเลิกใบกำกับภาษีอย่างย่อ
    # เลขที่ ..." ไม่มีคำว่าเดิมเลย จึงหลุด — เลขที่ยกเลิกไปโผล่เป็นเลขที่
    # ของใบนี้ ซึ่งถ้ายื่น ภ.พ.30 ไปคือยื่นผิดใบ
    # ใบนี้ใช้ป้าย "เลขที่" เปล่า ๆ ไม่ใช่ "เลขที่ใบกำกับภาษี" ประโยคยกเลิก
    # จึงแข่งกับกล่องหัวเอกสารที่ลำดับความสำคัญเดียวกัน และชนะเพราะอยู่ก่อน
    cancelled_clause = """บริษัท บีทูเอส จำกัด สาขาโรบินสันเชียงใหม่ สาขาที่ 00053
เลขประจำตัวผู้เสียภาษีอากร : 0105538032743
ใบเสร็จรับเงิน/ใบกำกับภาษี
เป็นการยกเลิกใบกำกับภาษีอย่างย่อเลขที่ 103-107827 วันที่ 22 กรกฎาคม 2568 และออกใบกำกับภาษีมีอิเล็กทรอนิกส์ใหม่แทน
เลขที่
วันที่
50051072510000079
23 กรกฎาคม 2568
"""
    all_ok &= check(
        "B2S wording: the cancelled document's number is not taken",
        extractor.extract_invoice_no(cancelled_clause) == "50051072510000079",
    )
    all_ok &= check(
        "B2S wording: the cancelled document's date is not taken either",
        extractor.extract_date(cancelled_clause)[1] == "2025-07-23",
    )

    # ---- "เลขที่" ในที่อยู่คือบ้านเลขที่ ไม่ใช่เลขที่เอกสาร ----
    # กับดักตัวจริงของใบ B2S หน้า 58: ที่อยู่ผู้ขายขึ้นต้นด้วย "เลขที่ 9
    # หมู่ 3 ..." และอยู่เหนือกล่องหัวเอกสาร ระบบจึงคืนรหัสไปรษณีย์ของ
    # ผู้ขาย (50200) มาเป็นเลขที่ใบกำกับภาษี — เลขที่ผิดสนิทและดูไม่ออก
    # ด้วยตาเพราะเป็นตัวเลขห้าหลักที่หน้าตาเหมือนเลขเอกสารสั้น ๆ
    address_trap = """B2S
บริษัท บีทูเอส จำกัด สาขาโรบินสันเชียงใหม่ สาขาที่ 00053
เลขที่ 9 หมู่ 3 ตำบลสุเทพ อำเภอเมืองเชียงใหม่ จังหวัดเชียงใหม่ 50200
เลขประจำตัวผู้เสียภาษีอากร : 0105538032743
เลขที่
วันที่
50051072510000079
22 กรกฎาคม 2568
ใบเสร็จรับเงิน/ใบกำกับภาษี
ที่อยู่ เลขที่ 239 ถนน ห้วยแก้ว ตำบล สุเทพ อำเภอ เมืองเชียงใหม่ จังหวัด เชียงใหม่ 50200
"""
    all_ok &= check(
        "a street address's house number is not the document number",
        extractor.extract_invoice_no(address_trap) == "50051072510000079",
    )
    all_ok &= check(
        "an address line is recognised by two or more locality words",
        extractor._looks_like_address(" 9 หมู่ 3 ตำบลสุเทพ อำเภอเมืองเชียงใหม่"),
    )
    all_ok &= check(
        "a plain document-number line is not mistaken for an address",
        not extractor._looks_like_address(" 50051072510000079"),
    )
    # คำเดียวไม่พอ — "เลขที่เอกสาร ... ถนน" อาจบังเอิญเจอได้ในใบที่ OCR
    # เอาบรรทัดมาต่อกัน จึงบังคับสองคำขึ้นไป
    all_ok &= check(
        "one locality word alone is not enough to call a line an address",
        not extractor._looks_like_address(" INV-2026-001 ถนน"),
    )

    # ---- ใบจริง เป๋าเปา: ชื่อผู้ซื้อกลายเป็นชื่อสินค้า ----
    pao = extractor.extract_fields(REAL_PAOPAO_RAW_TEXT, ocr_confidence=90.0)
    all_ok &= check("real paopao: buyer is the university faculty, not a product line",
                    pao["buyer_name"] == "คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่")
    all_ok &= check("real paopao: seller",
                    pao["seller_name"] == "ห้างหุ้นส่วนจำกัด เป่าเปา (สำนักงานใหญ่ )")
    all_ok &= check("real paopao: seller tax id", pao["seller_tax_id"] == "0503550005305")
    all_ok &= check("real paopao: invoice_no", pao["invoice_no"] == "POSS6807/2233")
    all_ok &= check("real paopao: date", pao["invoice_date_iso"] == "2025-07-22")
    all_ok &= check("real paopao: subtotal", pao["subtotal"] == 317.76)
    all_ok &= check("real paopao: vat", pao["vat"] == 22.24)
    all_ok &= check("real paopao: total", pao["total"] == 340.00)
    all_ok &= check("real paopao: เต็มรูป", pao["doc_type"] == "เต็มรูป")
    all_ok &= check("real paopao: nothing flagged", pao["review_reason"] is None)
    # หน่วยน้ำหนักไม่ใช่ชื่อหน่วยงานราชการ
    all_ok &= check("a weight in grams is not a government department",
                    not extractor.BUYER_ENTITY_HINT_RE.search("กระดาษAA 80แกรม 1*100"))
    all_ok &= check("...but a real government department still is",
                    bool(extractor.BUYER_ENTITY_HINT_RE.search("กรมสรรพากร")))

    # ---- ใบจริง B2S: สี่ปัญหาซ้อนกันในใบเดียว ----
    b2s = extractor.extract_fields(REAL_B2S_RAW_TEXT, ocr_confidence=90.0)
    all_ok &= check("real b2s: buyer name (label is the bare word ชื่อ)",
                    b2s["buyer_name"] == "คณะบริหารธุรกิจ มหาวิทยาลัยเชียงใหม่")
    all_ok &= check("real b2s: subtotal is the VATable line, not the exempt 0.00",
                    b2s["subtotal"] == 48.60)
    all_ok &= check("real b2s: vat is 3.40, not the VAT-inclusive 52.00",
                    b2s["vat"] == 3.40)
    all_ok &= check("real b2s: total (no total label on the page at all)",
                    b2s["total"] == 52.00)
    all_ok &= check("real b2s: the masked card number is not the VAT",
                    b2s["vat"] != 114100.0)
    all_ok &= check("real b2s: classified เต็มรูป, so the VAT stays claimable",
                    b2s["doc_type"] == "เต็มรูป")
    all_ok &= check("real b2s: invoice_no is not the cancelled one nor the postcode",
                    b2s["invoice_no"] == "50051072510000079")
    all_ok &= check("real b2s: date", b2s["invoice_date_iso"] == "2025-07-22")
    all_ok &= check("real b2s: seller tax id", b2s["seller_tax_id"] == "0105538032743")
    all_ok &= check("real b2s: the three amounts agree, so nothing is flagged",
                    b2s["review_reason"] is None)

    # ---- การสแกนทั้งหน้า: ต้องกล้าพอและขี้ขลาดพอ ----
    # กล้าพอ — เจอคำตอบได้แม้ตัวเลขสามตัวไม่ได้อยู่ติดกัน (เคส B2S)
    scattered = """48.60
ชำระโดย
3.40
Change
52.00
"""
    all_ok &= check(
        "the page-wide scan finds a triple whose parts are not adjacent",
        extractor._totals_from_number_run(scattered) == (48.60, 3.40, 52.00),
    )
    # ขี้ขลาดพอ — มีสองคำตอบเมื่อไหร่ ต้องยอมแพ้ ไม่ใช่เลือกเอาเอง
    ambiguous = """100.00
คั่น
7.00
คั่น
107.00
คั่น
200.00
คั่น
14.00
คั่น
214.00
"""
    all_ok &= check(
        "two possible triples on one page means give up, not guess",
        extractor._totals_from_number_run(ambiguous) is None,
    )
    # และต้องไม่ไปขุดเอาเลขที่ปนอยู่กลางรหัสมาเป็นเงิน
    all_ok &= check(
        "a number glued to letters is not a value",
        extractor._find_after_keyword("ภาษีมูลค่าเพิ่ม QRPP 114100XXXXXX6",
                                      extractor.VAT_KEYWORDS) is None,
    )
    all_ok &= check(
        "...but a plain amount on the same kind of line still is",
        extractor._find_after_keyword("ภาษีมูลค่าเพิ่ม 3.40",
                                      extractor.VAT_KEYWORDS) == "3.40",
    )

    # ---- VAT อัตราผสม (ของยกเว้นภาษีปนกับของ 7%) ----
    # ตัวเลขชุดนี้มาจากใบจริง: Makro หน้า 9 ของกอง "ใบจริงอันใหม่.pdf"
    #   แถว 1  0.00%   81.00                  0.00    81.00
    #   แถว 2  7.00%  195.33                 13.67   209.00
    #   TOTAL         276.33                 13.67   290.00
    # 276.33 + 13.67 = 290.00 ลงตัวเป๊ะ แต่ 13.67 เป็นเพียง 4.95% ของ
    # 276.33 เพราะกล้วยหอมในบิลเป็นของยกเว้นภาษี ใบนี้อ่านถูกทุกตัวเลข
    # แต่ระบบเดิมขึ้นเตือนทุกครั้ง — การเตือนใบที่ถูกอยู่แล้วอันตรายพอ ๆ
    # กับไม่เตือนใบที่ผิด เพราะทำให้คนเลิกอ่านคำเตือน
    mixed_numbers = {81.00, 195.33, 209.00, 276.33, 13.67, 290.00, 51.00,
                     158.00, 87.00, 296.00, 6.00, 29.00}
    all_ok &= check(
        "mixed-rate: the exempt portion is found and it is the printed 81.00",
        extractor._exempt_portion(276.33, 13.67, mixed_numbers) == 81.00,
    )
    all_ok &= check(
        "mixed-rate: a correctly-read mixed invoice raises no warning",
        extractor.totals_mismatch_reason(276.33, 13.67, 290.00, 81.00) is None,
    )
    all_ok &= check(
        "mixed-rate: reconcile leaves a correct mixed invoice untouched",
        extractor.reconcile_totals(276.33, 13.67, 290.00, mixed_numbers)
        == (276.33, 13.67, 290.00),
    )
    # ถ้าไม่มีหลักฐานบนกระดาษว่าใบนี้ผสม ก็ต้องไม่ยอมรับ — ข้อนี้คือตัวกันเดา
    all_ok &= check(
        "mixed-rate: no exempt split is invented when the page has no such numbers",
        extractor._exempt_portion(276.33, 13.67, {276.33, 13.67, 290.00}) is None,
    )
    all_ok &= check(
        "mixed-rate: a genuinely wrong pair is still rejected",
        extractor._exempt_portion(1000.00, 500.00, mixed_numbers) is None,
    )
    all_ok &= check(
        "mixed-rate: an unexplained VAT is still flagged",
        extractor.totals_mismatch_reason(1000.00, 500.00, 1500.00) is not None,
    )
    # แถวสรุปของกลุ่ม 7% (195.33/13.67/209.00) ก็บวกลงตัวในตัวเอง การสแกน
    # ต้องเลือกแถว TOTAL ของทั้งใบ ไม่ใช่แถวของกลุ่มเดียว
    all_ok &= check(
        "mixed-rate: the arithmetic scan picks the grand total row, not the 7% section",
        extractor._balanced_triple(
            [81.00, 195.33, 276.33, 0.00, 13.67, 13.67, 81.00, 209.00, 290.00],
            mixed_numbers,
        ) == (276.33, 13.67, 290.00),
    )
    # ...แต่ตัวเลขจากคนละใบที่บังเอิญบวกลงตัวทั้งคู่ ยังต้องถือว่ากำกวม
    all_ok &= check(
        "two unrelated balanced triples are still ambiguous",
        extractor._balanced_triple([100.00, 7.00, 107.00, 200.00, 14.00, 214.00])
        is None,
    )
    # ใบ 7% ธรรมดาต้องไม่เปลี่ยนพฤติกรรม แม้หน้านั้นจะมีตัวเลขเต็มไปหมด
    all_ok &= check(
        "an ordinary 7% invoice still reports exempt = 0",
        extractor._exempt_portion(332.71, 23.29, mixed_numbers) == 0.0,
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
