"""Entrypoint: `python -m estudo_geral_extractor.run [--keep-pdfs]`.

One-shot script (mirrors scraper/run.py's shape). For every DEI doctoral
thesis with `dc:date` >= 2024 in OAI set com_10316_255:
  1. GET the item landing page (issues the bot-gate cookies, and is where the
     real PDF download link lives — see download.py).
  2. GET the legacy REST API for clean, language-tagged metadata.
  3. Download the PDF (if the site actually serves one — an embargoed item's
     item page can still print a bitstream link that redirects to a login
     page instead; that is not a bug in this script, see download.py).
  4. Extract text, write `estudo_geral/<slug>.md` with full front-matter.

Writes `estudo_geral/manifest.json` summarizing every record's outcome, so
the delivered count is a query over that file, not a claim in a report.

PDFs are a cache, not an archive (PO decision, S3): the `.md` is the durable
artifact and `source_url` is the provenance — we reference the full document
at UC, we don't warehouse it. A PDF is discarded once its `.md` extraction
succeeds; it is kept only when extraction failed (so a re-run doesn't have to
re-download it to retry), or when `--keep-pdfs` opts back into keeping every
one. Either way the cache lives in the data dir
(`uc_phd_app.paths.estudo_geral_pdf_cache_dir()`), not this package's
`estudo_geral/` — that directory is wiped wholesale on every app update, and
the `.md` + manifest that DO belong there are meant to survive it.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from uc_phd_app import paths as app_paths

from . import oai, restapi
from .download import bootstrap_session, download_pdf, fetch_item_page, find_download_link
from .markdown import build_front_matter, handle_to_slug, render_markdown
from .pdftext import extract_text

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "estudo_geral"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

REQUEST_SPACING_SECONDS = 0.8


def throttle():
    time.sleep(REQUEST_SPACING_SECONDS)


def item_page_url(handle):
    return f"https://estudogeral.uc.pt/handle/{handle}"


def process_one(session, handle, keep_pdfs=False):
    """Returns a manifest entry dict. Never raises — every failure is recorded."""
    entry = {"handle": handle, "source_url": item_page_url(handle)}
    try:
        html = fetch_item_page(session, handle)
    except Exception as exc:  # noqa: BLE001 - one bad item must not abort the run
        entry["error"] = f"item page fetch failed: {exc}"
        return entry
    throttle()

    try:
        raw = restapi.fetch_item(session, handle)
    except Exception as exc:  # noqa: BLE001
        entry["error"] = f"REST metadata fetch failed: {exc}"
        return entry
    throttle()

    fields = restapi.parse_item_metadata(raw, handle)
    entry.update(
        {
            "title": fields["title"],
            "date": fields["date"],
            "rights": fields["rights"],
            "authors": fields["authors"],
        }
    )

    link = find_download_link(html)
    full_text = False
    body_text = ""
    if link is None:
        entry["download_error"] = "no download link found on item page"
    else:
        slug = handle_to_slug(handle)
        pdf_path = app_paths.estudo_geral_pdf_cache_dir() / f"{slug}.pdf"
        ok, status, error = download_pdf(session, link, pdf_path)
        throttle()
        if ok:
            pdf_bytes = pdf_path.stat().st_size
            body_text = extract_text(pdf_path)
            full_text = bool(body_text.strip())
            entry["pdf_bytes"] = pdf_bytes
            # PDFs are a cache, not an archive — discard once the .md has
            # the text, keep only on a failed extraction (so a retry has
            # something to re-extract from without re-downloading).
            if full_text and not keep_pdfs:
                pdf_path.unlink()
            else:
                entry["pdf_kept"] = True
        else:
            entry["download_error"] = f"HTTP {status}: {error}" if status else str(error)

    fields["full_text"] = full_text
    front_matter = build_front_matter(fields, entry["source_url"])
    md = render_markdown(front_matter, body_text)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{handle_to_slug(handle)}.md").write_text(md, encoding="utf-8")

    entry["full_text"] = full_text
    return entry


def main():
    ap = argparse.ArgumentParser(prog="estudo_geral_extractor.run")
    ap.add_argument("--keep-pdfs", action="store_true",
                     help="keep every downloaded PDF instead of discarding it "
                          "once its .md extraction succeeds")
    args = ap.parse_args()

    session = bootstrap_session()

    print("enumerating OAI-PMH ListRecords for set", oai.SET_SPEC, "from", oai.FROM_DATE, "...")
    records = list(oai.fetch_all_records(session, sleep=throttle))
    print(f"  {len(records)} records deposited since {oai.FROM_DATE} (deposit date, not publication year)")

    selected = oai.select_dei_doctoral_theses_2024_plus(records)
    print(f"  {len(selected)} are doctoralThesis with dc:date year >= 2024 (the actual population)")

    manifest = []
    full_text_count = 0
    for i, record in enumerate(selected, start=1):
        handle = record["handle"]
        print(f"[{i}/{len(selected)}] {handle} ...")
        entry = process_one(session, handle, keep_pdfs=args.keep_pdfs)
        manifest.append(entry)
        if entry.get("full_text"):
            full_text_count += 1
        else:
            reason = entry.get("download_error") or entry.get("error") or "unknown"
            print(f"  no full text: {reason}", file=sys.stderr)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"done. {len(manifest)} theses written to {OUTPUT_DIR}/, "
        f"{full_text_count}/{len(manifest)} with full text extracted."
    )


if __name__ == "__main__":
    main()
