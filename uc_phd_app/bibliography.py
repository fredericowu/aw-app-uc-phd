"""The bibliography — which works this corpus cites, and how often.

Derived, not collected: 23,316 distinct works and 24,559 citations, parsed
offline out of ``estudo_geral/*.md`` by ``analysis/build_bibliography.py`` and
read here out of the committed seed. Nothing in this module parses anything —
doing that per request would re-read 68 MB of markdown on every page load.

**Why a floor matters.** 22,609 of the 23,316 works — 97.0% — are cited by
exactly one thesis. That is not a parsing failure: 181 theses spanning ~20
years across six different DEI/CISUC research groups genuinely barely share a
bibliography. Ranking 23,316 rows by a citation count where 97% of them tie at
1 is not a ranking, it is an alphabetical list with a column of 1s. So the
ranked view applies ``DEFAULT_MIN_CITED_BY`` and the full list stays reachable
and searchable behind it — exactly the shape ``collab.py`` settled on for its
4,242 co-project pairs, and for the same reason.

**What this module cannot answer.** "Which works are most important to this
research community" is not what ``cited_by`` measures. Three things stand
between the two, and ``BIBLIOGRAPHY_CAVEAT`` says all three on screen:

* **Coverage is 133 of 181 theses** (95.7% of the 139 that have body text at
  all; the other 42 are metadata-only stubs). A work cited only by the 48
  theses this cannot read is invisible here, not rare.
* **Matching is two-tier and the second tier is lossy.** Measured against DOI
  ground truth, two theses citing the same work produce the same normalised
  key 52.6% of the time. So ``cited_by`` is a **floor**, not a count — the
  true figure is higher, unevenly, and a 1 may well be a 2.
* **A citation is not an endorsement.** A thesis cites work it refutes.

Those are limits of the data and the matcher, not caveats this module adds for
form's sake. They are why the default view ranks nothing below the floor.
"""
from __future__ import annotations

from . import db

#: Floor the ranked view applies unless a caller asks for everything. 2, not
#: 3: at 2 the table is 707 works — enough to read, and every row in it is a
#: work that genuinely connects at least two theses, which is the only thing
#: this dataset has to say that a per-thesis reference list does not. Pass
#: min_cited_by=1 to see all 23,316, which the UI offers explicitly.
DEFAULT_MIN_CITED_BY = 2

#: Kept separate from the floor above on purpose, the same way collab.py keeps
#: GRAPH_MIN_WEIGHT apart from DEFAULT_MIN_WEIGHT: this one answers "how many
#: rows fit on a screen", the other answers "which rows are worth ranking".
#: Folding them together would mean a paging tweak silently re-ranks the table.
MAX_PAGE_SIZE = 200

TIERS = ("doi", "title", "unmatched")

BIBLIOGRAPHY_CAVEAT = (
    "cited_by is the number of DISTINCT theses whose parsed bibliography "
    "contains this work — a floor, not a count. Three things push the true "
    "figure higher: references were parseable in 133 of 181 theses (42 are "
    "metadata-only stubs with no body text, 6 more have a body whose "
    "bibliography did not survive PDF extraction); matching two differently "
    "worded citations of one work succeeds 52.6% of the time at tier 'title', "
    "measured against DOI ground truth on every build; and PDF extraction "
    "corrupts word boundaries in both directions, which the normalised key "
    "absorbs but not perfectly. 97.0% of works here are cited exactly once — "
    "that is a real property of 181 theses across six research groups and ~20 "
    "years, not a bug, and it is why the ranked view applies a floor of at "
    "least 2 citing theses by default. Pass min_cited_by=1 to see everything."
)

MATCH_TIER_CAVEAT = (
    "match_tier says how a work's identity was established, and a count means "
    "something different in each. 'doi' is an exact match on a DOI that "
    "survived truncation checks — high precision, but sparse, since most "
    "entries carry no DOI. 'title' is a normalised first-author + title key "
    "with all whitespace and punctuation removed (the only normalisation that "
    "survives this corpus corrupting 'Technology' into 'Technol ogy' and "
    "'of dependability' into 'ofdependability' in the same sentence) — its "
    "recall against DOI ground truth is 52.6%. 'unmatched' is an entry no key "
    "could be derived from; those are singletons by construction and can "
    "never rank."
)

COVERAGE_CAVEAT = (
    "reference_count is what the parser extracted, not what the thesis cites. "
    "Zero means one of two different things, and full_text tells them apart: "
    "full_text = 0 is a metadata-only stub with no body text to parse, while "
    "full_text = 1 with zero references is a real body whose bibliography the "
    "parser could not find — a genuine miss worth looking at."
)


def summary() -> dict:
    """Headline counts plus the distribution the floor is justified by."""
    row = db.query("bibliography_summary")[0]
    histogram = {
        str(r["cited_by"]): r["reference_count"]
        for r in db.query("bibliography_cited_by_histogram")
    }
    return {
        **row,
        "cited_by_histogram": histogram,
        "match_tiers": db.query("bibliography_match_tiers"),
        "default_min_cited_by": DEFAULT_MIN_CITED_BY,
    }


def _escape_like(term: str) -> str:
    """``%``/``_``/``\\`` are wildcards in LIKE — same escaping as
    ``api/projects.py``'s project-title search and ``api/collab.py``'s person
    search. A user typing "%" means the character."""
    for ch in ("\\", "%", "_"):
        term = term.replace(ch, "\\" + ch)
    return f"%{term}%"


def references(
    min_cited_by: int = DEFAULT_MIN_CITED_BY,
    q: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """The ranked reference table, filtered and paged.

    Parameterised SQL inline rather than a committed ``sql/`` file, following
    ``api/collab.py``'s person search: ``db.query()`` takes no parameters, and
    interpolating a floor or a search term into a committed query string is
    the "query as a Python string literal" this repo forbids in the worse
    direction. The unparameterised aggregates this view is justified by *are*
    committed — see ``sql/bibliography_cited_by_histogram.sql``.
    """
    # Stripped once, up front: a term that only filters after .strip() but is
    # echoed back raw makes the UI show a "matching ' '" note for a search
    # that did not happen.
    term = (q or "").strip()
    where = ["cited_by >= :floor"]
    params: dict = {"floor": min_cited_by, "limit": limit, "offset": offset}
    if term:
        where.append("(display_string LIKE :like ESCAPE '\\' OR doi LIKE :like ESCAPE '\\')")
        params["like"] = _escape_like(term)
    if tier:
        where.append("match_tier = :tier")
        params["tier"] = tier
    clause = " AND ".join(where)

    total = db.one(f"SELECT COUNT(*) AS n FROM bib_references WHERE {clause}", params)["n"]
    rows = db.rows(
        f"""
        SELECT id, display_string, doi, year, first_author, match_tier,
               matcher_version, cited_by
        FROM bib_references
        WHERE {clause}
        ORDER BY cited_by DESC, first_author, display_string
        LIMIT :limit OFFSET :offset
        """,
        params,
    )
    return {
        "total": total,
        "min_cited_by": min_cited_by,
        "q": term or None,
        "tier": tier,
        "limit": limit,
        "offset": offset,
        "references": rows,
        "caveat": BIBLIOGRAPHY_CAVEAT,
        "match_tier_caveat": MATCH_TIER_CAVEAT,
    }


def citing_theses(reference_id: int) -> list[dict]:
    """The theses citing one work, each with that thesis's own wording.

    ``entry_raw`` is what makes the match checkable rather than asserted: two
    theses citing one work with visibly different strings is the evidence the
    match tier is claiming something about, and a reader can see for
    themselves whether the matcher was right.
    """
    return db.rows(
        """
        SELECT tr.handle, t.title, t.year, tr.entry_raw
        FROM thesis_references tr
        JOIN theses t ON t.handle = tr.handle
        WHERE tr.reference_id = :id
        ORDER BY t.year DESC, t.title
        """,
        {"id": reference_id},
    )


def reference(reference_id: int) -> dict | None:
    """One work plus the theses that cite it, or None if there is no such id."""
    row = db.one(
        """
        SELECT id, display_string, doi, year, first_author, match_tier,
               matcher_version, cited_by
        FROM bib_references WHERE id = :id
        """,
        {"id": reference_id},
    )
    if row is None:
        return None
    return {**row, "theses": citing_theses(reference_id), "caveat": BIBLIOGRAPHY_CAVEAT}


def per_thesis() -> dict:
    """How many references came out of each thesis, zeros included."""
    return {"theses": db.query("bibliography_per_thesis"), "caveat": COVERAGE_CAVEAT}
