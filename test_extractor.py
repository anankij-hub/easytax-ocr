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

# Mirrors a real vendor invoice layout reported by a user: 8-column item
# table (ลำดับ/รหัสสินค้า/รายการ/จำนวน/หน่วย/ราคา-หน่วย/ส่วนลด/จำนวนเงิน),
# whole-baht line amounts with no decimals, and a totals block that uses
# "มูลค่าหลังส่วนลด" / "จำนวนเงินทั้งสิ้น" (no "รวม") instead of the
# "รวมเป็นเงิน" / "จำนวนเงินรวมทั้งสิ้น" wording used elsewhere. The old
# extractor mis-parsed this as subtotal=13, vat=7 (just the "7" from "7%"),
# total=None, and 0 line items.
REAL_VENDOR_INVOICE_TEXT = """บริษัท รจนา จำกัด (สำนักงานใหญ่)
36/9 แขวงขุมทอง เขตลาดกระบัง กรุงเทพฯ 10250
เลขประจำตัวผู้เสียภาษี 0105558887774
โทร/แฟกซ์. 020-4567-902
ใบกำกับภาษี/ใบเสร็จรับเงิน
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
รวมเงิน 4,434.58
ส่วนลด 0.00
มูลค่าหลังส่วนลด 4,434.58
ภาษีมูลค่าเพิ่ม 7% 310.42
(สี่พันเจ็ดร้อยสี่สิบห้าบาทถ้วน)
จำนวนเงินทั้งสิ้น 4,745.00
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
    all_ok &= check("tax id checksum valid", extractor.validate_thai_tax_id(fields["seller_tax_id"]))
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

    # bad checksum should fail validation
    all_ok &= check("bad checksum rejected", extractor.validate_thai_tax_id("0105567123469") is False)

    # regression: real vendor invoice with an 8-column item table and
    # non-decimal line amounts (see comment on REAL_VENDOR_INVOICE_TEXT)
    fields3 = extractor.extract_fields(REAL_VENDOR_INVOICE_TEXT, ocr_confidence=88.0)
    print("\n--- Real vendor invoice fields ---")
    for k, v in fields3.items():
        print(f"  {k}: {v}")
    all_ok &= check("real invoice: invoice_no", fields3["invoice_no"] == "IV0100168-99")
    all_ok &= check("real invoice: subtotal = 4434.58 (not 13)", fields3["subtotal"] == 4434.58)
    all_ok &= check("real invoice: vat = 310.42 (not 7)", fields3["vat"] == 310.42)
    all_ok &= check("real invoice: total = 4745.0 (not None)", fields3["total"] == 4745.0)
    all_ok &= check("real invoice: 4 line items extracted", len(fields3["line_items"]) == 4)
    if fields3["line_items"]:
        first = fields3["line_items"][0]
        all_ok &= check("real invoice: item1 description", first["description"] == "ปากกาลูกลื่น (1*24)")
        all_ok &= check("real invoice: item1 qty=1", first["qty"] == 1)
        all_ok &= check("real invoice: item1 unit_price=135", first["unit_price"] == 135)
        all_ok &= check("real invoice: item1 amount=135", first["amount"] == 135)

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
