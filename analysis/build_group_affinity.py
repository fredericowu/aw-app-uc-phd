"""Build the content half of thesis -> research-group attribution into the seed.

``python -m analysis.build_group_affinity``

Reads ``theses`` / ``thesis_keywords`` and ``projects`` / ``project_groups`` /
``project_keywords`` out of ``data/cisuc.sqlite3``, scores every thesis
against every research group by TF-IDF cosine, and writes
``thesis_group_affinity(handle, group_code, score, rank)`` back into the same
file.

**Why this exists at all.** A thesis's group used to be the union of its
author's and supervisors' own groups, which asks "where has this supervisor
worked" when the question is "what is this thesis about" — 35 of 181 theses
came out tagged with all six groups (S7). This is the second, independent
signal: it reads the thesis itself and never looks at a person. Neither
signal is trusted alone; ``uc_phd_app/theses.py`` combines them by whether
they agree, and their disagreement is what the ``contested`` tier reports.

**Why TF-IDF and not the embeddings.** ``documents.abstract_embedding``
already exists in Postgres, and ``uc_phd_app/api/fit.py`` already measured
what it does on this corpus: everything here is computing research, so
embedding distances compress — top-1 to top-5 spans 0.007. Six
computing-group profiles would sit closer together than two theses do. IDF
does the opposite: it actively up-weights the vocabulary that *separates*
the groups, which is the entire job. It also keeps the dashboard off
Postgres — today only ``api/search.py`` and ``api/fit.py`` degrade to 503,
and a down vector store must not blank the group column. This is the
falsifiable part of the decision: measure the embedding top-1/top-2 margin
against the lexical one this script reports, and if it wins, flip it.

**Why offline.** Same reason ``analysis/build_thesis_facts.py`` is offline:
TF-IDF over 400 synopses on every ``/api/theses`` request is absurd, the
output is reviewable in a diff, and the app opens the database ``mode=ro``.

**Two clocks, stated plainly.** The people half of the attribution stays
derived live per request (a person's group is a live fact about their
career). This half is frozen here. A cisuc.uc.pt re-scrape moves one and not
the other until this script re-runs — that is a real seed-rebuild obligation,
not an implementation detail.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scraper" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "cisuc.sqlite3"

#: Tokens shorter than this are dropped outright. Three, not two, because the
#: Portuguese corpus is full of two-letter clitics and the English one of
#: "of"/"in" — none of which the stop-list below would have to enumerate.
MIN_TOKEN_LEN = 3

#: Portuguese and English function words. Deliberately short: IDF already
#: flattens anything that appears in most documents, so this only has to
#: catch the words frequent enough to survive a 581-document IDF and still
#: add noise. Both languages are in one list because both abstracts go into
#: one bag — 131 PT and 129 EN, against a mostly-English project corpus. A
#: PT-only thesis is therefore scored on weaker evidence; that is a known
#: weakness of this choice and part of why the confidence tier exists rather
#: than a bare group label.
STOP_WORDS = frozenset(
    """
    the and for are but not with that this from was were has have had its
    which whose where when what who how all any can could should would may
    might must into onto over under than then them they their there these
    those such been being does did done also more most other some only very
    each both about after before between during through while because
    against among within without upon here also thus hence
    que uma umas uns dos das nas nos por para com como mais mas nao sao foi
    seu sua seus suas pelo pela pelos pelas este esta estes estas esse essa
    isso aquele aquela sobre entre desde ate quando onde qual quais cujo
    cuja tambem ser ter sido tem tinha muito pouco todos todas cada outro
    outra outros outras seja sendo nesta neste nessa nesse deste desta
    forma modo caso vez vezes parte partes
    abstract resumo tese thesis doutoramento phd universidade coimbra
    trabalho work study estudo research pesquisa project projeto projecto
    results resultados objetivo objectivo proposed proposta approach
    abordagem based baseado paper artigo new novo nova
    """.split()
)

#: How many times each field is repeated into its document's token bag.
#: Keywords are the most deliberate description a document carries — an
#: author or a project coordinator chose them — so they outweigh a title,
#: which outweighs prose the writer produced at length.
THESIS_FIELD_WEIGHTS = (("title", 2), ("keywords", 3), ("abstract_en", 1), ("abstract_pt", 1))
PROJECT_FIELD_WEIGHTS = (("title", 1), ("synopsis", 1), ("keywords", 3))

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str | None) -> list[str]:
    """Lowercase, accent-stripped alphanumeric tokens, stop-words removed.

    Accents are folded rather than preserved because the same term is written
    both ways across the two corpora (``optimização``/``optimizacao``,
    ``inteligência``/``inteligencia``) and a split vocabulary would silently
    halve the evidence for exactly the domain terms that separate groups.

    Deliberately *not* ``analysis.name_match.tokenize``: that one is tuned for
    human names (it drops Portuguese nobiliary connectors and keeps
    one-letter initials), which is the opposite of what prose needs.
    """
    if not text:
        return []
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [
        token
        for token in _TOKEN_RE.findall(folded)
        if len(token) >= MIN_TOKEN_LEN and token not in STOP_WORDS
    ]


def _weighted_bag(fields: dict[str, str | None], weights: tuple[tuple[str, int], ...]) -> list[str]:
    bag: list[str] = []
    for name, weight in weights:
        bag += tokenize(fields.get(name)) * weight
    return bag


def thesis_documents(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """One token bag per thesis: title x2 + keywords x3 + both abstracts.

    **A title on its own is not a content signal.** 9 of the 181 theses carry
    no keyword and no abstract in either language, and a title is four or five
    tokens — cosine against a bag of sixty project synopses will still rank
    six groups off that, confidently and meaninglessly. Those theses get an
    empty bag, which ``affinity_rows`` turns into no rows, which the reader
    reports as "no content signal" rather than a group. The title is kept, and
    weighted, for every thesis that has something to anchor it to.

    Kept as an empty list rather than dropped from the dict so the caller can
    tell "scored nothing" from "was never considered".
    """
    keywords: dict[str, list[str]] = {}
    for handle, keyword in conn.execute(
        "SELECT handle, keyword FROM thesis_keywords ORDER BY handle, ordinal"
    ):
        keywords.setdefault(handle, []).append(keyword)

    docs = {}
    for handle, title, abstract_en, abstract_pt in conn.execute(
        "SELECT handle, title, abstract_en, abstract_pt FROM theses"
    ):
        fields = {
            "title": title,
            "keywords": " ".join(keywords.get(handle, ())),
            "abstract_en": abstract_en,
            "abstract_pt": abstract_pt,
        }
        described = any(fields[name] for name in ("keywords", "abstract_en", "abstract_pt"))
        docs[handle] = _weighted_bag(fields, THESIS_FIELD_WEIGHTS) if described else []
    return docs


def project_documents(conn: sqlite3.Connection) -> dict[int, list[str]]:
    """One token bag per project: title + synopsis + keywords x3."""
    keywords: dict[int, list[str]] = {}
    for project_id, keyword in conn.execute(
        "SELECT project_id, keyword FROM project_keywords ORDER BY project_id, ordinal"
    ):
        keywords.setdefault(project_id, []).append(keyword)

    docs = {}
    for project_id, title, synopsis in conn.execute("SELECT id, title, synopsis FROM projects"):
        docs[project_id] = _weighted_bag(
            {
                "title": title,
                "synopsis": synopsis,
                "keywords": " ".join(keywords.get(project_id, ())),
            },
            PROJECT_FIELD_WEIGHTS,
        )
    return docs


def group_documents(
    conn: sqlite3.Connection, projects: dict[int, list[str]]
) -> dict[str, list[str]]:
    """One token bag per research group: every one of its projects', concatenated.

    A project in two groups contributes to both, the same many-to-many the
    rest of this app keeps being honest about. Every group in
    ``research_groups`` gets an entry even with no projects, so a group can
    never disappear from a ranking by accident.
    """
    docs: dict[str, list[str]] = {
        row[0]: [] for row in conn.execute("SELECT code FROM research_groups")
    }
    for project_id, group_code in conn.execute(
        "SELECT project_id, group_code FROM project_groups ORDER BY project_id"
    ):
        if group_code in docs:
            docs[group_code] += projects.get(project_id, [])
    return docs


def inverse_document_frequency(documents: list[list[str]]) -> dict[str, float]:
    """Smoothed IDF over the *source* corpus — the theses and the individual
    projects, never the six group bags.

    The group bags are concatenations of hundreds of projects, so almost every
    term appears in all six; an IDF computed over them would be ~0 everywhere
    and the cosine would collapse to raw term overlap. IDF has to be measured
    where documents are genuinely about one thing.
    """
    total = len(documents)
    document_frequency: Counter = Counter()
    for tokens in documents:
        document_frequency.update(set(tokens))
    return {
        term: math.log((1 + total) / (1 + df)) + 1.0 for term, df in document_frequency.items()
    }


def tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """L2-normalised sublinear-TF x IDF.

    Sublinear TF (``1 + log tf``) matters more than usual here: a group bag is
    ~60 projects of prose and a thesis bag is a few hundred tokens, so raw
    counts would let a group's most-repeated word dominate every comparison.
    Returns ``{}`` for an empty bag — the caller reads that as "no content
    signal", which is a real state (6 of 181 theses have no text at all).
    """
    counts = Counter(tokens)
    vector = {
        term: (1.0 + math.log(count)) * idf[term]
        for term, count in counts.items()
        if term in idf
    }
    norm = math.sqrt(sum(weight * weight for weight in vector.values()))
    if not norm:
        return {}
    return {term: weight / norm for term, weight in vector.items()}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    """Both sides are already L2-normalised, so the dot product *is* the cosine."""
    if len(right) < len(left):
        left, right = right, left
    return sum(weight * right.get(term, 0.0) for term, weight in left.items())


def affinity_rows(
    theses: dict[str, list[str]],
    groups: dict[str, list[str]],
    idf: dict[str, float],
) -> list[tuple]:
    """``(handle, group_code, score, rank)`` for every thesis x group pair that
    scores above zero, ranked 1..n within each thesis.

    A zero-scoring pair is *not* written. That is what makes "this thesis has
    no content signal at all" representable — no rows for the handle — instead
    of a six-way tie at 0.0 that an argmax would happily resolve into a
    confident-looking group.
    """
    group_vectors = {code: tfidf_vector(tokens, idf) for code, tokens in groups.items()}
    rows = []
    for handle in sorted(theses):
        thesis_vector = tfidf_vector(theses[handle], idf)
        scored = [
            (code, cosine(thesis_vector, group_vector))
            for code, group_vector in group_vectors.items()
        ]
        # Sort by code as the tiebreak so a rebuild is byte-stable: dict order
        # would otherwise decide the rank of two equally-scoring groups.
        scored = [pair for pair in sorted(scored, key=lambda p: (-p[1], p[0])) if pair[1] > 0]
        rows += [
            (handle, code, round(score, 6), rank)
            for rank, (code, score) in enumerate(scored, start=1)
        ]
    return rows


def margins(rows: list[tuple]) -> dict:
    """Relative margin of top-1 over top-2, per thesis, as percentiles.

    Reported because it is the honest measure of how much this signal should
    be trusted: a median margin in the single digits is a real ranking and
    still far too soft to be shown alone, which is precisely why
    ``uc_phd_app/theses.py`` only believes it when the people signal agrees.
    """
    by_handle: dict[str, list[float]] = {}
    for handle, _code, score, _rank in rows:
        by_handle.setdefault(handle, []).append(score)
    values = sorted(
        (scores[0] - scores[1]) / scores[0]
        for scores in by_handle.values()
        if len(scores) > 1 and scores[0] > 0
    )
    if not values:
        return {}
    return {
        f"p{p}": round(values[min(len(values) - 1, int(len(values) * p / 100))], 4)
        for p in (10, 50, 90)
    }


def build(db_path: Path) -> dict:
    """Rebuild ``thesis_group_affinity`` from scratch. Returns what it wrote."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        theses = thesis_documents(conn)
        projects = project_documents(conn)
        groups = group_documents(conn, projects)
        idf = inverse_document_frequency([*theses.values(), *projects.values()])
        rows = affinity_rows(theses, groups, idf)

        # Full replace, for the same reason build_thesis_facts.py does it: the
        # table is a pure function of the seed, and a thesis withdrawn upstream
        # must not leave its affinity behind.
        conn.execute("DELETE FROM thesis_group_affinity")
        conn.executemany("INSERT INTO thesis_group_affinity VALUES (?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()

    scored = {handle for handle, _code, _score, _rank in rows}
    return {
        "theses": len(theses),
        "projects": len(projects),
        "groups": len(groups),
        "vocabulary": len(idf),
        "affinity_rows": len(rows),
        "theses_scored": len(scored),
        "theses_without_content": sorted(set(theses) - scored),
        "top1_over_top2_relative_margin": margins(rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    report = build(args.db)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
