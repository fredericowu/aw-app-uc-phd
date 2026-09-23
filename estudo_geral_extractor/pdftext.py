"""PDF -> plain text, for the body of each thesis's .md.

Not unit-tested against a fixture PDF: pypdf's extraction is a thin wrapper
over its own parser internals, and a synthetic single-page fixture would not
exercise anything a real ~50-300 page thesis does (fonts, embargo pages,
scanned images) — same reasoning tests/test_parse.py gives for staying out of
scraper/'s fetch path. Exercised for real by run.py against all 17 live PDFs.
"""
from pypdf import PdfReader


def extract_text(pdf_path):
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return "\n\n".join(pages)
