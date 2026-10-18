"""Entrypoint: `python -m estudo_geral_extractor.run [--keep-pdfs]`.

One-shot script (mirrors scraper/run.py's shape). Enumerates every community
in `oai.HARVEST_SETS` (DEI, INESCC, ISR, IT — no publication-year floor),
merges the doctoral theses by handle so a cross-listed one is seen once, and
then, per thesis:

  * **already on disk** — rewrite its front matter with the OAI origin the
    enumeration just reported, body untouched, no network. This is how the
    pre-existing corpus is backfilled: the record headers carry full set
    membership whichever set they were reached through, so re-enumerating is
    the backfill and there is no second mechanism to maintain.
  * **new** — the full pipeline:
      1. GET the item landing page (issues the bot-gate cookies, and is where
         the real PDF download link lives — see download.py).
      2. GET the legacy REST API for clean, language-tagged metadata.
      3. Download the PDF (if the site actually serves one — an embargoed
         item's item page can still print a bitstream link that redirects to a
         login page instead; that is not a bug in this script, see
         download.py).
      4. Extract text, write `estudo_geral/<slug>.md` with full front-matter.

Writes `estudo_geral/manifest.json` summarizing every record's outcome, so
the delivered count is a query over that file, not a claim in a report. The
manifest is MERGED, not rewritten: a thesis that was only re-rendered keeps
the outcome of the run that actually downloaded it, because nothing about
that outcome changed.

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
from .markdown import build_front_matter, handle_to_slug, render_markdown, rewrite_front_matter
from .pdftext import extract_text

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "estudo_geral"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

REQUEST_SPACING_SECONDS = 0.8


def throttle():
    time.sleep(REQUEST_SPACING_SECONDS)


def item_page_url(handle):
    return f"https://estudogeral.uc.pt/handle/{handle}"


def read_md_verbatim(path):
    """An existing `.md` read with newline translation OFF.

    `Path.read_text` is universal-newlines: it turns every CR and CRLF into a
    LF, and writing that back would silently rewrite 24 of the committed
    theses whose extracted PDF body carries bare CRs — thousands of changed
    lines in a diff whose whole job is to be the added `oai_sets` lines. The
    front matter itself has no CRs, so only the read/write boundary needs
    this; `yaml.safe_dump` emits LF and keeps doing so.
    """
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def write_md_verbatim(path, text):
    """Counterpart of `read_md_verbatim` — no newline translation on the way out."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def merge_by_handle(selected_by_set):
    """Pure: {set_spec: [record, ...]} -> one record per handle, first set wins.

    The same thesis is routinely listed under DEI *and* an institute, and
    processing it twice would download one PDF twice and write one `.md`
    twice. First-seen wins rather than last because it makes no difference:
    every record's header carries the item's complete set membership, so the
    copy reached through DEI already knows it is also in ISR.

    Set iteration order (and therefore output order) is `HARVEST_SETS`'s, so
    two runs over an unchanged repository produce the same manifest order.
    """
    population = {}
    for records in selected_by_set.values():
        for record in records:
            population.setdefault(record["handle"], record)
    return list(population.values())


def load_manifest(path):
    """The previous run's manifest, keyed by handle. Empty on a first run."""
    if not path.exists():
        return {}
    return {entry["handle"]: entry for entry in json.loads(path.read_text(encoding="utf-8"))}


def carried_forward_entry(old_entry, handle, oai_sets):
    """Pure: the manifest entry for a thesis whose `.md` was only re-rendered.

    Its recorded outcome — full text, download errors, kept PDF — is still
    exactly true, because this run did not re-fetch anything. So it is
    carried across verbatim with only the newly recorded origin added, rather
    than replaced by a thinner entry that would read as a thesis we fetched
    and learned nothing about.
    """
    entry = dict(old_entry) if old_entry else {"handle": handle, "source_url": item_page_url(handle)}
    entry["oai_sets"] = list(oai_sets)
    return entry


def process_one(session, handle, oai_sets, keep_pdfs=False):
    """Returns a manifest entry dict. Never raises — every failure is recorded."""
    entry = {"handle": handle, "source_url": item_page_url(handle), "oai_sets": list(oai_sets)}
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
            entry["pdf_bytes"] = pdf_bytes
            try:
                body_text = extract_text(pdf_path)
            except Exception as exc:  # noqa: BLE001 - a malformed PDF must not abort the run
                entry["extract_error"] = f"{type(exc).__name__}: {exc}"
                body_text = ""
            full_text = bool(body_text.strip())
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
    front_matter = build_front_matter(fields, entry["source_url"], oai_sets)
    md = render_markdown(front_matter, body_text)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # PDF text extraction occasionally yields lone UTF-16 surrogate codepoints
    # (malformed source PDFs), which strict utf-8 encoding rejects outright.
    (OUTPUT_DIR / f"{handle_to_slug(handle)}.md").write_text(md, encoding="utf-8", errors="replace")

    entry["full_text"] = full_text
    return entry


def main():
    ap = argparse.ArgumentParser(prog="estudo_geral_extractor.run")
    ap.add_argument("--keep-pdfs", action="store_true",
                     help="keep every downloaded PDF instead of discarding it "
                          "once its .md extraction succeeds")
    args = ap.parse_args()

    session = bootstrap_session()

    selected_by_set = {}
    for set_spec, label in oai.HARVEST_SETS.items():
        print(f"enumerating OAI-PMH ListRecords for {set_spec} ({label}, "
              f"full history, no deposit-date floor) ...")
        records = list(oai.fetch_all_records(session, set_spec=set_spec, sleep=throttle))
        selected = oai.select_dei_doctoral_theses(records)
        print(f"  {len(records)} records in the set, {len(selected)} are doctoralThesis")
        selected_by_set[set_spec] = selected
        throttle()

    population = merge_by_handle(selected_by_set)
    print(f"merged population: {len(population)} distinct doctoral theses across "
          f"{len(selected_by_set)} sets "
          f"({sum(len(s) for s in selected_by_set.values())} set memberships)")

    old_manifest = load_manifest(MANIFEST_PATH)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    rewritten = 0
    full_text_count = 0
    for i, record in enumerate(population, start=1):
        handle = record["handle"]
        oai_sets = record["set_specs"]
        md_path = OUTPUT_DIR / f"{handle_to_slug(handle)}.md"
        if md_path.exists():
            # Backfill, not a re-harvest: the enumeration already told us the
            # origin, so there is nothing left to fetch for this thesis.
            write_md_verbatim(md_path, rewrite_front_matter(read_md_verbatim(md_path), oai_sets))
            if handle not in old_manifest:
                print(f"  {handle}: .md on disk with no manifest entry — synthesising one",
                      file=sys.stderr)
            entry = carried_forward_entry(old_manifest.get(handle), handle, oai_sets)
            rewritten += 1
        else:
            print(f"[{i}/{len(population)}] NEW {handle} ...")
            entry = process_one(session, handle, oai_sets, keep_pdfs=args.keep_pdfs)
            if not entry.get("full_text"):
                reason = (entry.get("download_error") or entry.get("extract_error")
                          or entry.get("error") or "unknown")
                print(f"  no full text: {reason}", file=sys.stderr)
        manifest.append(entry)
        if entry.get("full_text"):
            full_text_count += 1

    # A handle the sets no longer return is NOT quietly dropped from the
    # manifest and left as an orphan .md: say so here, and let
    # analysis/build_thesis_facts.py's reconcile refuse the seed rebuild. A
    # thesis withdrawn upstream is a decision for a human, not for this run.
    vanished = sorted(set(old_manifest) - {entry["handle"] for entry in manifest})
    if vanished:
        print(f"WARNING: {len(vanished)} handle(s) in the old manifest were returned by no "
              f"harvested set: {vanished}", file=sys.stderr)

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"done. {len(manifest)} theses in {OUTPUT_DIR}/ "
        f"({rewritten} front matter rewritten in place, {len(manifest) - rewritten} newly "
        f"harvested), {full_text_count}/{len(manifest)} with full text extracted."
    )


if __name__ == "__main__":
    main()
