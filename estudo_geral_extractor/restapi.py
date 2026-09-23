"""Legacy `/rest/` JSON API — richer than OAI-PMH: language-tagged titles,
abstracts and subjects, a single clean `dc.rights`, and the bitstream list
with real sizes. OAI-PMH is only used for enumeration (oai.py); every field
that lands in front-matter comes from here.

`/rest/bitstreams/<id>/retrieve` is broken (self-redirect loop, confirmed by
isolation) — never call it. Bitstream metadata here is used to know whether a
PDF exists and how big it should be, not to fetch it (see download.py).
"""
import requests

REST_BASE = "https://estudogeral.uc.pt/rest"


def fetch_item(session, handle):
    """Network: resolve a handle to its full REST item record (metadata + bitstreams)."""
    r = session.get(f"{REST_BASE}/handle/{handle}", params={"expand": "metadata,bitstreams"}, timeout=30)
    r.raise_for_status()
    return r.json()


def _values(metadata, key, language=None):
    out = []
    for m in metadata:
        if m["key"] != key:
            continue
        if language is not None and m.get("language") != language:
            continue
        out.append(m["value"])
    return out


def parse_item_metadata(raw, handle):
    """Pure: raw REST item JSON -> the fields this extractor cares about.

    Titles/abstracts are language-tagged in this API (unlike oai_dc, where
    element order is not a reliable language signal) — prefer 'eng', fall
    back to whatever exists so a Portuguese-only record doesn't lose its title.
    """
    metadata = raw.get("metadata") or []

    titles_eng = _values(metadata, "dc.title", "eng") + _values(metadata, "dc.title.alternative", "eng")
    titles_any = _values(metadata, "dc.title") + _values(metadata, "dc.title.alternative")
    title = (titles_eng or titles_any or [None])[0]

    abstract_en = "\n\n".join(_values(metadata, "dc.description.abstract", "eng"))
    abstract_pt = "\n\n".join(_values(metadata, "dc.description.abstract", "por"))

    authors = _values(metadata, "dc.contributor.author")
    supervisors = _values(metadata, "dc.contributor.advisor")
    date = (_values(metadata, "dc.date.issued") or [None])[0]
    keywords = _values(metadata, "dc.subject")
    rights = (_values(metadata, "dc.rights") or [None])[0]

    bitstreams = raw.get("bitstreams") or []
    pdf_bitstreams = [b for b in bitstreams if (b.get("mimeType") or "").lower() == "application/pdf"]

    return {
        "handle": handle,
        "title": title,
        "authors": authors,
        "supervisors": supervisors,
        "date": date,
        "keywords": keywords,
        "abstract_en": abstract_en,
        "abstract_pt": abstract_pt,
        "rights": rights,
        "pdf_bitstreams": [
            {"id": b["id"], "name": b["name"], "size_bytes": b.get("sizeBytes")} for b in pdf_bitstreams
        ],
    }
