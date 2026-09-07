"""OCR wrapper for the Vercel deployment.

Vercel serverless functions can't run a system binary like Tesseract (no
apt-get, and the function bundle size/cold-start would be painful even if
it could). So this version calls the Google Cloud Vision API over HTTP
instead — same DOCUMENT_TEXT_DETECTION idea as Tesseract, but hosted, and
generally more accurate for Thai text out of the box.

extractor.py is completely unaffected by this swap: it only cares about
the plain-text output + a confidence score, which both engines provide
through the same process_upload() interface.

Requires the GOOGLE_VISION_API_KEY environment variable (set it in the
Vercel project's Environment Variables). See DEPLOY.md for how to create one.
"""
import os
import io
import base64
import requests

try:
    import pypdf
except ImportError:
    pypdf = None

VISION_IMAGES_URL = "https://vision.googleapis.com/v1/images:annotate"
VISION_FILES_URL = "https://vision.googleapis.com/v1/files:annotate"
LANGUAGE_HINTS = ["th", "en"]


def _api_key():
    key = os.environ.get("GOOGLE_VISION_API_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_VISION_API_KEY is not set. Add it in Vercel project settings "
            "(Settings -> Environment Variables). See DEPLOY.md for how to create one."
        )
    return key


def _page_confidence(page):
    """Cloud Vision reports per-symbol confidence; average it up to a
    page-level 0-100 score similar to what Tesseract's image_to_data gives."""
    scores = []
    for block in page.get("blocks", []):
        conf = block.get("confidence")
        if conf is not None:
            scores.append(conf)
    if not scores:
        return 0.0
    return (sum(scores) / len(scores)) * 100


def ocr_image_bytes(image_bytes):
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": LANGUAGE_HINTS},
        }]
    }
    resp = requests.post(VISION_IMAGES_URL, params={"key": _api_key()}, json=payload, timeout=25)
    resp.raise_for_status()
    result = resp.json()["responses"][0]
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "Cloud Vision API error"))
    annotation = result.get("fullTextAnnotation", {})
    text = annotation.get("text", "")
    pages = annotation.get("pages", [])
    conf = _page_confidence(pages[0]) if pages else 0.0
    return text, conf


def ocr_pdf_bytes(pdf_bytes, max_pages=5):
    """Cloud Vision's synchronous files:annotate supports up to 5 pages per
    request for PDFs — fine for typical single/few-page tax invoices."""
    payload = {
        "requests": [{
            "inputConfig": {
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
                "mimeType": "application/pdf",
            },
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": LANGUAGE_HINTS},
            "pages": list(range(1, max_pages + 1)),
        }]
    }
    resp = requests.post(VISION_FILES_URL, params={"key": _api_key()}, json=payload, timeout=55)
    resp.raise_for_status()
    responses = resp.json()["responses"][0].get("responses", [])

    pages_out = []
    for i, r in enumerate(responses):
        if "error" in r:
            continue
        annotation = r.get("fullTextAnnotation", {})
        text = annotation.get("text", "")
        pages = annotation.get("pages", [])
        conf = _page_confidence(pages[0]) if pages else 0.0
        pages_out.append({
            "text": text, "confidence": conf, "source_page": i + 1, "method": "cloud-vision-pdf",
        })
    return pages_out


def pdf_text_if_available(pdf_bytes):
    """If the PDF already has an embedded text layer, use it directly —
    faster, free, and more accurate than OCR. Returns None if no usable
    text layer is found."""
    if pypdf is None:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        if len("\n".join(pages_text).strip()) > 40:
            return pages_text
    except Exception:
        pass
    return None


def process_upload(filename, file_bytes):
    """Same interface as the local/Tesseract version: returns a list of
    {"text", "confidence", "source_page", "method"} dicts, one per page."""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        text_pages = pdf_text_if_available(file_bytes)
        if text_pages:
            return [
                {"text": t, "confidence": 100.0, "source_page": i + 1, "method": "pdf-text"}
                for i, t in enumerate(text_pages)
            ]
        return ocr_pdf_bytes(file_bytes)

    text, conf = ocr_image_bytes(file_bytes)
    return [{"text": text, "confidence": conf, "source_page": 1, "method": "cloud-vision"}]
