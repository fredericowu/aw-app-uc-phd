"""The thesis corpus, read from the seed and joined to CISUC research groups.

Two halves that must stay apart, and did not before this module was rewritten.

**Identity is frozen.** "Which person is `Carvalho, Paulo Fernando Pereira
de`?" is answered once, offline, by ``analysis/name_match.py``, and committed
into ``thesis_people``. It used to be answered by re-parsing 18 YAML front
matters on every request against a hand-verified JSON file — fine at 18
theses, not at the 181 the corpus is growing to, and not once the advisor
view, the collaboration graph and the theme recommendation each need the same
join. Each of them now queries this one table instead of inventing a fourth
notion of who a person is.

**Groups stay live.** A matched person's research group is still re-derived
on every request from ``project_people`` / ``project_groups``, exactly as
before. That is deliberate and worth keeping verbatim: a group is a live fact
about a person's project history, not something to freeze into a thesis row.
Rebuilding the seed must never be what it takes for a new project to move
someone's group. What changed in S7 is only the *shape* of that derivation —
a weighted share instead of a flat set (``sql/person_group_shares.sql``).

**A thesis's group is two signals, combined by agreement.** The people signal
above answers "where do this thesis's people work"; the content signal
(``thesis_group_affinity``, built offline by
``analysis/build_group_affinity.py``) answers "what is this thesis about".
Unioning the people signal alone gave 2.70 of 6 groups per thesis with 35 of
181 carrying all six — correct, and useless. Neither signal is strong enough
to be believed alone, so ``_attribution`` shows one group where they
corroborate each other and two, ranked and flagged, where they do not. Note
the consequence: the two halves run on **two clocks** — the people half moves
the moment a project is scraped, the content half only when the builder
re-runs.

A name the matcher could not resolve is still a row here, carrying
``name_raw`` and its tier — never dropped, never guessed. ``identity_coverage``
below reports how many, at the grain each view actually consumes, rather than
this docstring carrying a figure that goes stale on every reindex;
``docs/thesis-attribution.md`` has the full record, the two deliberate
near-misses, and the two rule relaxations that were measured and rejected.
"""
from __future__ import annotations

from pathlib import Path

from . import db, paths

#: Carried with the theses payload. A thesis shows one group when the two
#: signals agree and two when they do not — never the six a union used to
#: produce.
GROUP_CAVEAT = (
    "A thesis's research group is decided by two independent signals: what "
    "its author/supervisors' own project history weighs towards, and what "
    "its own text looks like against each group's projects. They agree on "
    "one group (shown as one), or they disagree (both shown, ranked and "
    "flagged as contested). Only one signal available shows that one group; "
    "neither available leaves the thesis unattributed rather than guessed. "
    "A thesis therefore counts towards at most two groups, so these counts "
    "sum to slightly more than the corpus size."
)

ATTRIBUTION_NOTE = (
    "Estudo Geral publishes no research-group field, so attribution is "
    "derived. Signal 1 (people): each author/supervisor name is resolved to a "
    "person once, offline, by a deterministic matcher (analysis/name_match.py) "
    "that tiers every decision exact/confident/ambiguous/unmatched and never "
    "guesses; each resolved person's groups are then weighted by how much of "
    "their project history sits in each (coordinator roles counting more than "
    "researcher ones) rather than flattened into a set — which is what used to "
    "tag a prolific supervisor's students with their supervisor's entire "
    "career. Signal 2 (content): TF-IDF cosine between the thesis's own title, "
    "keywords and abstracts and each group's project text, built offline by "
    "analysis/build_group_affinity.py. Neither is trusted alone — both are "
    "weak rankings, and the tier reports whether they corroborate each other. "
    "Full record: docs/thesis-attribution.md."
)

#: Rendered beside ``identity_coverage()``. Its job is to say which of those
#: numbers is a gap and which is the correct answer — because the largest one
#: (a third of author names unresolved) is NOT a gap, and a reader shown a
#: bare percentage will assume every miss is a defect. It also refuses the
#: obvious "fix": two rule relaxations were implemented and measured against
#: the real corpus, both bought a handful of edges with a confidently wrong
#: person, and both left the golden fixture green.
IDENTITY_COVERAGE_NOTE = (
    "Coverage is reported per role and per grain because one pooled number "
    "describes neither population. Author names resolve least often and that "
    "is the correct answer, not a gap: `people` holds current CISUC staff, "
    "and a doctoral student is not staff — expect roughly a third of author "
    "names to stay unresolved and do not read it as a defect. The supervisor "
    "side is the one the advisor and collaboration views depend on, and it is "
    "reported at the edge grain (a supervisor on ten theses is ten advisor "
    "edges, not one name) as well as per thesis. Resolution also degrades by "
    "decade, because staff lists are current and a 1990s supervisor may have "
    "left: nothing can match its way past that. The matcher never guesses — "
    "it tiers every decision and leaves a name unresolved rather than picking "
    "a plausible person; two attempts to relax it were measured and rejected "
    "for producing confidently wrong people (docs/thesis-attribution.md)."
)

#: Tiers that mean "this is a person". ``ambiguous`` is deliberately not one
#: of them: more than one real person fits, and picking either is the guess
#: this whole module exists to avoid.
RESOLVED_TIERS = ("exact", "confident")

#: How much a thesis-person's own group shares count towards the thesis.
#: A supervisor's research identity is the thesis's subject far more reliably
#: than a doctoral student's is — the student is usually new, and their only
#: CISUC projects (if any) are the supervisor's. Scaled further by the
#: matcher's own ``match_confidence``, so a ``confident`` name pulls less than
#: an ``exact`` one without needing a separate rule.
ROLE_WEIGHTS = {"supervisor": 1.0, "author": 0.5}

#: The four honest outcomes of combining the two signals, plus the one that
#: means neither exists. ``contested`` is not a failure state: 63 of 181
#: theses genuinely land here, and showing both candidates ranked is the
#: whole point — the alternative is averaging two weak signals into one
#: confident-looking group that neither of them supports.
CORROBORATED = "corroborated"
CONTESTED = "contested"
PEOPLE_ONLY = "people-only"
CONTENT_ONLY = "content-only"
UNATTRIBUTED = "unattributed"


def _person_group_shares(slug: str, db_path: Path | None = None) -> dict[str, float]:
    """One person's raw (un-normalised) group weights — see
    ``sql/person_group_shares.sql`` for why the normalisation is not in the
    query."""
    return {
        row["group_code"]: row["weight"]
        for row in db.rows(db.load_query("person_group_shares"), {"slug": slug}, db_path)
    }


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    """Scale to sum 1. ``{}`` stays ``{}`` — an empty signal must not become a
    uniform one, which is what dividing by a zero total guarded with a
    fallback would quietly do."""
    total = sum(weights.values())
    if not total:
        return {}
    return {code: weight / total for code, weight in weights.items()}


def _top(scores: dict[str, float]) -> str | None:
    """The argmax, ties broken by group code so a rebuild is stable."""
    if not scores:
        return None
    return min(scores, key=lambda code: (-scores[code], code))


def _resolve_person_rows(rows: list[dict], db_path: Path | None = None,
                          with_groups: bool = True) -> list[dict]:
    """Collapse the ``thesis_people`` rows for one (name, role) into the shape
    the dashboard renders.

    ``status`` stays "matched"/"unattributed" — the frontend's existing
    contract — and the finer ``match_status`` tier rides alongside it, so a
    later view can distinguish "nobody fits" from "two people fit" without
    this one changing.

    ``with_groups=False`` skips the per-person group lookup for callers that
    must not display a group anyway (``supervisors_for``, for the Fit screen —
    see its docstring). ``groups`` stays present and empty so the returned
    shape does not fork.

    ``group_shares`` is the weighted form of ``groups`` — the same codes, with
    how much of the person's project history sits in each, summing to 1.
    **It is normalised per name, not per slug, and that is load-bearing**:
    ``thesis_people``'s key is ``(handle, name_raw, role, person_slug)`` and
    one human can hold two rows in ``people`` (``joao-bicker`` /
    ``joao-bicker-1``), so a name resolving to both would otherwise contribute
    twice as much weight to the thesis as a name resolving to one — the exact
    double-count this function already avoids for identity.
    """
    by_name: dict[str, dict] = {}
    slug_cache: dict[str, dict[str, float]] = {}
    raw_weights: dict[str, dict[str, float]] = {}
    for row in rows:
        entry = by_name.get(row["name_raw"])
        if entry is None:
            resolved = row["match_status"] in RESOLVED_TIERS
            entry = by_name[row["name_raw"]] = {
                "name": row["name_raw"],
                "status": "matched" if resolved else "unattributed",
                "match_status": row["match_status"],
                "confidence": row["match_confidence"],
                "note": row["match_note"],
                "matched": [],
                "groups": [],
                "group_shares": {},
            }
            raw_weights[row["name_raw"]] = {}
        if entry["status"] != "matched" or row["person_slug"] is None:
            continue
        entry["matched"].append({"slug": row["person_slug"], "name": row["person_name"]})
        if not with_groups:
            continue
        slug = row["person_slug"]
        if slug not in slug_cache:
            slug_cache[slug] = _person_group_shares(slug, db_path)
        for code, weight in slug_cache[slug].items():
            raw_weights[row["name_raw"]][code] = raw_weights[row["name_raw"]].get(code, 0.0) + weight
    for name_raw, entry in by_name.items():
        entry["group_shares"] = _normalise(raw_weights[name_raw])
        entry["groups"] = sorted(entry["group_shares"])
    return list(by_name.values())


def _people_signal(people: list[tuple[str, list[dict]]]) -> dict[str, float]:
    """The first signal: where this thesis's *people* work, as shares summing
    to 1 across the groups any of them touch.

    Summed rather than union'd, which is the whole change. A supervisor who
    coordinates 15 SSE projects and one apiece in five other groups used to
    contribute all six equally; now SSE carries most of their weight and the
    argmax says so. The shares are what make that legible in the payload
    rather than only inside the ranking.
    """
    scores: dict[str, float] = {}
    for role, resolved in people:
        weight = ROLE_WEIGHTS[role]
        for person in resolved:
            factor = weight * person["confidence"]
            for code, share in person["group_shares"].items():
                scores[code] = scores.get(code, 0.0) + share * factor
    return _normalise(scores)


def _attribution(people_shares: dict[str, float], content_scores: dict[str, float]) -> dict:
    """Combine the two signals by whether they **agree**, never by averaging.

    Both are weak on their own — the content ranking's median top-1-over-top-2
    margin is under 10% — so a blended score would produce a single confident
    group that neither signal actually supports. Agreement is the strongest
    evidence this data holds: measured over the real corpus the two pick the
    same group far more often than chance, and where they diverge that
    divergence *is* the finding, so it is shown as a ranked pair rather than
    resolved by picking a favourite.

    The people signal leads a contested pair. Not because it is better — it is
    the one built on a person's actual, recorded project membership, whereas
    the content side is a lexical similarity, so it is the more defensible
    thing to read first when a reader only reads one.
    """
    people_top = _top(people_shares)
    content_top = _top(content_scores)

    if people_top and content_top:
        codes = [people_top] if people_top == content_top else [people_top, content_top]
        tier = CORROBORATED if people_top == content_top else CONTESTED
    elif people_top:
        codes, tier = [people_top], PEOPLE_ONLY
    elif content_top:
        codes, tier = [content_top], CONTENT_ONLY
    else:
        codes, tier = [], UNATTRIBUTED

    return {
        "tier": tier,
        "ranked": [
            {
                "code": code,
                "people_share": round(people_shares.get(code, 0.0), 4),
                "content_score": round(content_scores.get(code, 0.0), 4),
            }
            for code in codes
        ],
    }


def thesis_count(db_path: Path | None = None) -> int:
    """Corpus size straight from ``COUNT(*)`` — no join, no attribution work.
    For anything that only needs the number (e.g. the MCP tool descriptions
    in ``uc_phd_app/mcp/http_handler.py``), not the full ``list_theses()``
    resolution."""
    row = db.one("SELECT COUNT(*) AS n FROM theses", (), db_path)
    return row["n"] if row else 0


def list_theses(db_path: Path | None = None) -> list[dict]:
    """Every thesis, with its author/supervisors resolved to a CISUC person
    (or flagged unattributed) and its research group(s) decided by the two
    signals ``_attribution`` combines.

    ``groups`` stays a plain sorted list of codes — the frontend's chips
    (``ui/src/views/Theses.jsx``) and the MCP group filter
    (``uc_phd_app/mcp/tools.py``) read it unchanged. It is now at most two
    codes long. ``group_attribution`` rides alongside with the tier and the
    two per-group scores behind it, for anything that wants to show *why*.
    """
    people_rows = db.rows(db.load_query("thesis_people"), (), db_path)
    by_handle: dict[str, dict[str, list[dict]]] = {}
    for row in people_rows:
        by_handle.setdefault(row["handle"], {}).setdefault(row["role"], []).append(row)

    content: dict[str, dict[str, float]] = {}
    for row in db.rows(db.load_query("thesis_group_affinity"), (), db_path):
        content.setdefault(row["handle"], {})[row["group_code"]] = row["score"]

    theses = []
    for thesis in db.rows(db.load_query("theses"), (), db_path):
        roles = by_handle.get(thesis["handle"], {})
        authors = _resolve_person_rows(roles.get("author", []), db_path)
        supervisors = _resolve_person_rows(roles.get("supervisor", []), db_path)
        attribution = _attribution(
            _people_signal([("author", authors), ("supervisor", supervisors)]),
            content.get(thesis["handle"], {}),
        )
        groups = sorted(entry["code"] for entry in attribution["ranked"])
        theses.append(
            {
                "handle": thesis["handle"],
                "title": thesis["title"],
                "source_url": thesis["source_url"],
                "year": thesis["year"],
                "rights": thesis["rights"],
                "full_text": bool(thesis["full_text"]),
                "authors": authors,
                "supervisors": supervisors,
                "groups": groups,
                "attributed": bool(groups),
                "group_attribution": attribution,
            }
        )
    return theses


def supervisors_for(handles: list[str], db_path: Path | None = None) -> dict[str, list[dict]]:
    """Supervisors only, keyed by thesis handle — what the Fit screen names
    next to each matched thesis.

    Reads the same committed ``sql/thesis_people.sql`` ``list_theses`` does and
    filters in Python. At 18 theses / 50 name rows the whole table is smaller
    than the round trip to fetch part of it, and it keeps one committed query
    as the single definition of a thesis-person edge rather than a second,
    subtly-different one.

    Two deliberate narrowings against ``list_theses``:

    * **``role == 'supervisor'`` only.** A project ``coordinator`` is never an
      orientador and this app does not blur the two; ``thesis_people`` has no
      coordinator role precisely so that conflation cannot be re-introduced by
      a query. Authors are irrelevant here — the screen answers "who could
      supervise this", not "who wrote it".
    * **No research groups.** ``_resolve_person_rows`` resolves them and this
      drops them. Originally because attribution yielded 3.72 of 6 groups per
      thesis and meant nothing (S7); that is fixed, but the reason to keep the
      field off this screen survives it — a *person's* group list is still the
      un-weighted set, and it is the thesis-level combination, not this, that
      S7 made trustworthy. Cut from v1 by the PO; the cheapest way to honour
      that is not to carry the field at all.

    An unresolved name keeps its row, its ``name_raw`` and its
    ``match_status`` — never dropped, never guessed. That is what the LEFT
    JOIN in the committed query exists for.
    """
    wanted = set(handles)
    by_handle: dict[str, list[dict]] = {h: [] for h in wanted}
    rows = db.rows(db.load_query("thesis_people"), (), db_path)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if row["handle"] in wanted and row["role"] == "supervisor":
            grouped.setdefault(row["handle"], []).append(row)
    for handle, person_rows in grouped.items():
        by_handle[handle] = [
            {
                "name": person["name"],
                "status": person["status"],
                "match_status": person["match_status"],
                "matched": person["matched"],
            }
            for person in _resolve_person_rows(person_rows, db_path, with_groups=False)
        ]
    return by_handle


def identity_coverage(db_path: Path | None = None) -> dict:
    """How far the name -> person spine reaches, at every grain the advisor and
    collaboration views consume.

    Replaces a single flat ``{tier: name_count}`` dict, which was the wrong
    shape for two reasons measured over the 181-thesis corpus
    (``docs/thesis-attribution.md`` has the full record):

    * **It pooled authors with supervisors.** Those two populations have
      opposite expected outcomes — a doctoral student's absence from `people`
      (current CISUC staff) is the *correct* answer, an absent supervisor is a
      real hole — so one pooled 32.9%-unmatched rate described neither.
    * **It counted names, and the views consume edges.** A supervisor on ten
      theses is one name and ten advisor edges; the name grain understates what
      a single failure costs and the views degrade at the edge grain.

    Numbers only. The prose that says which of these is expected rather than a
    gap is ``IDENTITY_COVERAGE_NOTE``, shipped beside it — same split as
    ``group_breakdown`` / ``GROUP_CAVEAT``.
    """
    tiers: dict[str, dict[str, int]] = {}
    for row in db.rows(db.load_query("thesis_match_tiers"), (), db_path):
        tiers.setdefault(row["role"], {})[row["match_status"]] = row["name_count"]

    # One row of scalar subqueries, so there is always exactly one — no
    # None guard, same as collab.summary()'s db.one() calls.
    row = db.one(db.load_query("thesis_attribution_coverage"), (), db_path)
    return {
        "tiers_by_role": tiers,
        "names": {
            "author": {
                "total": row["author_names"],
                "resolved": row["author_names_resolved"],
            },
            "supervisor": {
                "total": row["supervisor_names"],
                "resolved": row["supervisor_names_resolved"],
            },
        },
        "supervision_edges": {
            "total": row["supervision_edges"],
            "resolved": row["supervision_edges_resolved"],
        },
        "theses": {
            "total": row["theses_total"],
            "listing_a_supervisor": row["theses_listing_a_supervisor"],
            "with_a_resolved_supervisor": row["theses_with_a_resolved_supervisor"],
            "fully_resolved": row["theses_fully_resolved"],
        },
        "co_supervision_pairs": {
            "total": row["co_supervision_pairs"],
            "resolved": row["co_supervision_pairs_resolved"],
        },
        "supervisor_people": row["supervisor_people"],
    }


def group_breakdown(theses: list[dict]) -> dict:
    """Per-group thesis counts (many-to-many, see ``GROUP_CAVEAT``) plus how
    many theses resolved to no group at all.

    Still many-to-many, but a contested thesis now contributes to exactly two
    groups instead of a supervisor's whole career contributing to six, so
    these counts sum to at most twice the corpus rather than 2.7x it.
    """
    counts: dict[str, int] = {}
    unattributed = 0
    for thesis in theses:
        if not thesis["groups"]:
            unattributed += 1
            continue
        for code in thesis["groups"]:
            counts[code] = counts.get(code, 0) + 1
    return {"counts": counts, "unattributed": unattributed}


def tier_breakdown(theses: list[dict]) -> dict[str, int]:
    """How many theses landed in each confidence tier.

    Reported next to the data for the same reason ``match_tiers`` is: the
    corroborated share is the honest measure of how much this attribution can
    be trusted, and burying it would let a single-group chip look equally
    certain everywhere. Every tier is present even at zero, so a reader can
    see that ``unattributed`` is 3 rather than wonder whether it was omitted.
    """
    counts = {
        tier: 0 for tier in (CORROBORATED, CONTESTED, PEOPLE_ONLY, CONTENT_ONLY, UNATTRIBUTED)
    }
    for thesis in theses:
        counts[thesis["group_attribution"]["tier"]] += 1
    return counts


def get_thesis(handle: str, db_path: Path | None = None, *, with_body: bool = True) -> dict | None:
    """One thesis's full record for ``uc_phd_app/mcp``'s ``get_phd_thesis``
    tool (S4) — everything ``list_theses()`` already resolves (identity,
    groups) plus the two abstracts it doesn't surface, and (by default) the
    extracted body text. ``None`` if the handle does not exist.

    ``with_body=False`` skips the ``thesis_body()`` read — the detail HTTP
    route (S5) needs the metadata header without paying for up to 1.2 MB of
    text it would discard; the MCP tool keeps the default so its contract is
    unchanged.

    Reuses ``list_theses()`` rather than a second identity join: at 18
    theses a linear scan is cheap, and it keeps the resolution logic in one
    place instead of two SQL paths drifting apart.
    """
    match = next((t for t in list_theses(db_path) if t["handle"] == handle), None)
    if match is None:
        return None
    row = db.one(db.load_query("thesis_by_handle"), {"handle": handle}, db_path)
    return {
        **match,
        "abstract_pt": row["abstract_pt"] if row else None,
        "abstract_en": row["abstract_en"] if row else None,
        "body": thesis_body(handle) if with_body else None,
    }


def thesis_body(handle: str) -> str | None:
    """The extracted markdown body for one thesis, read from its committed
    ``estudo_geral/<handle>.md`` (S1) — title + abstracts live in the seed
    (``theses`` table), but the full extracted text does not, so this reads
    the source file directly rather than duplicating it into the database.

    ``None`` when the file does not exist (an unindexed or embargoed-with-no-
    extraction thesis). Splitting on the front-matter delimiter is
    deliberately re-implemented here rather than imported from
    ``estudo_geral_extractor`` — see that package's own
    ``split_front_matter()`` docstring for why: it is expected to be deleted
    by another card, and this app's coverage gate cannot depend on it.
    """
    filename = handle.replace("/", "-") + ".md"
    path = paths.estudo_geral_dir() / filename
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return raw
    end = raw.find("\n---\n", 4)
    if end == -1:
        return raw
    return raw[end + len("\n---\n"):].lstrip("\n")
