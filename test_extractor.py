"""Unit tests for extractor.py that don't require a real OCR/Tesseract run.

These feed in text that approximates what Tesseract would output for a
Thai tax invoice, so we can validate the regex/field-extraction logic on
its own. Run: python3 test_extractor.py
"""
import extractor

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
