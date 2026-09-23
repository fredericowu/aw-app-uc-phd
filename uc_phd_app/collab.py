"""The collaboration graph — who works with whom, and who co-supervises.

Derived, not collected (docs/graph-db-plan.md's live-people-feed proposal
stays valid for what it uniquely offers — publication counts — but is not a
prerequisite here): 4,242 co-project pairs and 53 co-supervision pairs, both
computable offline from data already in the seed (``project_people``,
``thesis_people``). NetworkX territory, not Neo4j — a third consumer now
exists alongside the ranked table and the person-anchored neighbourhood: a
node-link graph (``graph()``/``build_graph()`` below), allowed precisely
because it is always drawn behind a floor — see ``GRAPH_MIN_WEIGHT``.

Two edge kinds, kept distinct, never summed:

* ``co_project``   — weight = number of projects two people were both listed
  on (any role), from ``project_people``.
* ``co_supervision`` — weight = number of theses two people co-supervised
  together, from ``thesis_people`` (``role='supervisor'``).

Both are computed from a LONG-FORM query (one row per pair x shared item)
aggregated here in Python, so every pair keeps ``shared_ids`` — the ids of
the actual projects/theses behind its weight. That is what lets the graph
answer "what do these two work on together?" instead of only "how much".
Only ``/collab/graph`` exposes it; see ``api/collab.py``.

**Why a floor matters.** Of the 4,242 co_project pairs, most exist because
two people happened to share exactly one project — a real but close to
meaningless signal on its own. Callers apply ``DEFAULT_MIN_WEIGHT`` unless
told otherwise; see ``CO_PROJECT_CAVEAT``.

**Why normalised weight is a second column, not a replacement.** A 30-person
project creates 435 pairs by itself — every one of those pairs' raw weight
grows the same amount a pair working alone on a 2-person project would for
sharing one project, which reads as "these two collaborate a lot" when the
truth is "they were both named on a big project". ``weight_normalized``
divides each shared project's contribution by ``(team_size - 1)`` (Newman's
collaboration weighting), so a pair's contribution to a giant project is
worth a fraction of a pair's contribution to a two-person one. The raw
``weight`` stays the default sort and the one the card's own numbers are
measured against; normalised is offered alongside it, not instead of it.

**What this module cannot answer.** "como se ajudam e se complementam" (how
people help and complement each other) needs more than edge weight — two
people can co-author five projects and think identically, or co-author one
and be each other's only bridge to a different subfield. The closest proxy
this data supports is ``cross_group``: whether two collaborators' own
project histories touch disjoint research groups. That is a co-occurrence
signal, not a measured complementarity — ``CROSS_GROUP_CAVEAT`` says so
explicitly rather than dressing it up.
"""
from __future__ import annotations

from . import db

#: Applied by default to the ranked /collab/pairs table for co_project —
#: pass min_weight=1 to see every pair including the near-meaningless ones.
DEFAULT_MIN_WEIGHT = {"co_project": 2, "co_supervision": 1}

#: Floor the GRAPH defaults to. Kept separate from DEFAULT_MIN_WEIGHT on
#: purpose: that constant answers "which pairs are worth listing" for the
#: ranked table; this one answers "how many marks fit on a screen" for the
#: node-link graph. Folding them into one constant would mean a future
#: rendering tweak silently re-ranks the table. co_project's floor of 3
#: (577 edges / 132 nodes) still read as a dense, hard-to-parse core in a
#: screenshot of the actual rendering — moved to 4 (282 edges / 91 nodes),
#: where individual hubs are visibly distinguishable, with that screenshot
#: as the evidence (PO pre-authorised this exact move without a re-scope).
#: co_supervision stays pinned at 1 — every weight >= 2 pair is a degenerate
#: 4-edge graph (histogram {1: 49, 2: 3, 5: 1}), not a network.
GRAPH_MIN_WEIGHT = {"co_project": 4, "co_supervision": 1}

KINDS = ("co_project", "co_supervision")

#: What one entry of an edge's ``shared_ids`` IS, per kind — the word the UI
#: puts in front of the tooltip ("3 shared projects" / "2 shared theses").
#: Kept here rather than hardcoded in the frontend because the noun is a
#: property of the edge kind, which this module defines.
#:
#: The plural is carried explicitly rather than left to the caller to build,
#: because "thesis" + "s" is "thesiss" — which is exactly what shipped to the
#: live app for about ten minutes. English morphology is not something a JSX
#: template should be guessing at.
SHARED_NOUN = {"co_project": "project", "co_supervision": "thesis"}
SHARED_NOUN_PLURAL = {"co_project": "projects", "co_supervision": "theses"}

CO_PROJECT_CAVEAT = (
    "weight is the raw count of projects two people were both listed on "
    "(COUNT(DISTINCT project_id) over project_people — its composite PK "
    "lets one person hold both coordinator and researcher roles on the same "
    "project, which would otherwise double-count it). Of the 4,242 pairs, "
    "most share exactly one project — a near-meaningless signal alone — so "
    "the ranked table applies a floor of at least 2 shared projects by "
    "default; pass min_weight=1 to see everything. weight_normalized "
    "additionally divides each shared project's contribution by "
    "(team size - 1), so a large project does not inflate every pair on it "
    "the same as two people working alone would inflate theirs — it is a "
    "secondary column, not the default ranking, because the raw count is "
    "what 'shared N projects' plainly means and what this feature's own "
    "measured numbers refer to."
)

CO_SUPERVISION_CAVEAT = (
    "weight is the number of theses two people co-supervised together, "
    "restricted to supervisor rows with a resolved person_slug — an "
    "unmatched supervisor name is not a graph node (see "
    "thesis_people.match_status). A handful of supervisor names on the real "
    "theses do not resolve to a person and are silently excluded here, the "
    "same way an unresolved name is excluded from every other per-person "
    "figure in this app."
)

CROSS_GROUP_CAVEAT = (
    "cross_group is co-occurrence, not complementarity: true only when "
    "neither person's own project history shares a research group with the "
    "other's (their group memberships are fully disjoint), null when either "
    "person has no project group membership to compare against, false "
    "otherwise. A true cross_group means two people who work together "
    "despite sitting in different groups on paper — it is not a measure of "
    "how well they complement each other, which this data cannot answer."
)

DEGREE_CAVEAT = (
    "degree is the count of distinct collaborators at the current floor, "
    "not a centrality measure — it counts people, not projects, so someone "
    "on one 30-person project has degree 29 at floor 1 and (usually) 0 at "
    "floor 3. degree_full is the same count with the floor removed (floor "
    "1) and is never what sizes a node — it only ever appears on hover."
)


def _co_project_pairs() -> list[dict]:
    """Aggregates ``sql/collab_co_project.sql``'s long form into one row per
    pair. Kept in Python rather than a second committed query, the same way
    ``api/projects.py`` pivots ``top_coordinators`` from long to wide —
    ``weight_normalized`` needs each shared project's own team size, which
    only exists at the long-form grain."""
    agg: dict[tuple[str, str], dict] = {}
    for row in db.query("collab_co_project"):
        key = (row["person_a"], row["person_b"])
        entry = agg.get(key)
        if entry is None:
            entry = {
                "person_a_slug": row["person_a"],
                "person_b_slug": row["person_b"],
                "weight": 0,
                "weight_normalized": 0.0,
                "shared_ids": [],
            }
            agg[key] = entry
        entry["weight"] += 1
        entry["shared_ids"].append(row["project_id"])
        team_size = row["team_size"]
        if team_size > 1:
            entry["weight_normalized"] += 1.0 / (team_size - 1)
    for entry in agg.values():
        entry["weight_normalized"] = round(entry["weight_normalized"], 3)
    return list(agg.values())


def _co_supervision_pairs() -> list[dict]:
    """Aggregates ``sql/collab_co_supervision.sql``'s long form the same way
    ``_co_project_pairs`` does. ``weight_normalized`` stays None: thesis
    teams are small (2-3 supervisors), so the quadratic-inflation concern
    that motivates co_project's normalisation does not apply."""
    agg: dict[tuple[str, str], dict] = {}
    for row in db.query("collab_co_supervision"):
        key = (row["person_a"], row["person_b"])
        entry = agg.get(key)
        if entry is None:
            entry = {
                "person_a_slug": row["person_a"],
                "person_b_slug": row["person_b"],
                "weight": 0,
                "weight_normalized": None,
                "shared_ids": [],
            }
            agg[key] = entry
        entry["weight"] += 1
        entry["shared_ids"].append(row["handle"])
    return list(agg.values())


def _pairs_for(kind: str) -> list[dict]:
    if kind == "co_project":
        return _co_project_pairs()
    if kind == "co_supervision":
        return _co_supervision_pairs()
    raise ValueError(f"unknown collaboration kind: {kind!r}")


def person_groups() -> dict[str, set[str]]:
    """slug -> set(research group code), from every project (any role) that
    person has ever been listed on. A person with no project membership at
    all (a supervisor with no CISUC project history) is simply absent —
    callers treat a missing key the same as an empty set."""
    groups: dict[str, set[str]] = {}
    for row in db.query("collab_person_groups"):
        groups.setdefault(row["person_slug"], set()).add(row["group_code"])
    return groups


def _cross_group(groups_a: set[str] | None, groups_b: set[str] | None) -> bool | None:
    if not groups_a or not groups_b:
        return None
    return groups_a.isdisjoint(groups_b)


def _person_names() -> dict[str, str]:
    return {row["slug"]: row["name"] for row in db.rows("SELECT slug, name FROM people")}


def _shared_titles(kind: str) -> dict:
    """id -> title for whatever an edge of ``kind`` is made of: project ids
    for co_project, thesis handles for co_supervision. A flat id->title
    lookup, the same shape (and the same inline-SELECT precedent) as
    ``_person_names`` — not a committed ``sql/`` query, because there is no
    figure here, only a label."""
    if kind == "co_project":
        return {row["id"]: row["title"] for row in db.rows("SELECT id, title FROM projects")}
    return {row["handle"]: row["title"] for row in db.rows("SELECT handle, title FROM theses")}


def enriched_pairs(kind: str) -> list[dict]:
    """Every pair for ``kind``, with names, group lists and ``cross_group``
    attached. The unfiltered, unsorted base every endpoint builds on."""
    if kind not in KINDS:
        raise ValueError(f"unknown collaboration kind: {kind!r}")
    names = _person_names()
    groups = person_groups()
    pairs = _pairs_for(kind)
    for pair in pairs:
        a, b = pair["person_a_slug"], pair["person_b_slug"]
        ga, gb = groups.get(a), groups.get(b)
        pair["person_a"] = names.get(a, a)
        pair["person_b"] = names.get(b, b)
        pair["person_a_groups"] = sorted(ga) if ga else []
        pair["person_b_groups"] = sorted(gb) if gb else []
        pair["cross_group"] = _cross_group(ga, gb)
    return pairs


def build_graph(pairs: list[dict], min_weight: int) -> dict:
    """Pure: aggregates already-enriched ``pairs`` (see ``enriched_pairs``)
    into a node-link graph at ``min_weight``, touching no database. Kept
    separate from ``graph()`` so degree — a new figure the shared test
    fixture cannot exercise (it has exactly one edge per kind) — is testable
    with hand-written pair dicts instead of a widened fixture.

    Degree is computed twice in one pass: ``degree`` counts only edges that
    survive the floor (the sole number allowed to size a node — see
    DEGREE_CAVEAT), ``degree_full`` counts every edge regardless of floor
    (hover-only, costs nothing extra since ``pairs`` already has them all).
    A node appears in ``nodes`` only if its ``degree >= 1`` — nodes derive
    from surviving edges, so degree 0 is impossible by construction and an
    isolated person is simply absent, not a zero-degree node.

    Each surviving edge carries ``shared_ids`` — WHICH projects/theses the
    edge stands for, not just how many. Ids, never titles: at floor 4 there
    are 1,869 edge x project rows but only 266 distinct projects, so
    inlining titles costs 124 KB against 22 KB for the ids plus one flat
    ``shared_labels`` dictionary (``graph()`` builds it, this pure function
    cannot — it has no database)."""
    people: dict[str, dict] = {}

    def touch(slug: str, name: str, groups: list[str]) -> dict:
        person = people.get(slug)
        if person is None:
            person = {
                "slug": slug,
                "name": name,
                "groups": groups,
                "degree": 0,
                "degree_full": 0,
            }
            people[slug] = person
        return person

    edges = []
    for pair in pairs:
        a = touch(pair["person_a_slug"], pair["person_a"], pair["person_a_groups"])
        b = touch(pair["person_b_slug"], pair["person_b"], pair["person_b_groups"])
        a["degree_full"] += 1
        b["degree_full"] += 1
        if pair["weight"] < min_weight:
            continue
        a["degree"] += 1
        b["degree"] += 1
        edges.append(
            {
                "source": pair["person_a_slug"],
                "target": pair["person_b_slug"],
                "weight": pair["weight"],
                "weight_normalized": pair["weight_normalized"],
                "cross_group": pair["cross_group"],
                "shared_ids": pair["shared_ids"],
            }
        )

    nodes = [p for p in people.values() if p["degree"] >= 1]
    nodes.sort(key=lambda p: (-p["degree"], p["name"]))
    max_degree = max((n["degree"] for n in nodes), default=0)
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "max_degree": max_degree,
    }


def graph(kind: str, min_weight: int) -> dict:
    """DB-backed wrapper: ``build_graph`` over ``enriched_pairs(kind)``. See
    ``build_graph`` for why degree is computed here rather than in a
    committed ``sql/collab_degree.sql`` — the floor is a request parameter
    and ``db.query()`` takes none, so a parameterised query cannot run
    through the loader, and interpolating the floor into SQL is exactly the
    'query as a Python string literal' this repo forbids elsewhere."""
    if kind not in KINDS:
        raise ValueError(f"unknown collaboration kind: {kind!r}")
    result = build_graph(enriched_pairs(kind), min_weight)
    # One flat id -> title dictionary for every id any SURVIVING edge names,
    # not the whole table: the floor is what decides how much of it is worth
    # sending, and an id no edge references is a label nothing can show.
    needed = {i for edge in result["edges"] for i in edge["shared_ids"]}
    titles = _shared_titles(kind)
    result["shared_labels"] = {i: titles[i] for i in needed if i in titles}
    result["shared_noun"] = SHARED_NOUN[kind]
    result["shared_noun_plural"] = SHARED_NOUN_PLURAL[kind]
    result["kind"] = kind
    result["min_weight"] = min_weight
    return result


def summary() -> dict:
    """Headline counts for the weight-distribution check the design notes
    ask for — surfaced on screen rather than left for someone to discover by
    scrolling a table."""
    total_people = db.one("SELECT COUNT(*) AS n FROM people")["n"]
    multi_project_people = db.one(
        """
        SELECT COUNT(*) AS n FROM (
            SELECT person_slug FROM (
                SELECT DISTINCT project_id, person_slug FROM project_people
            ) GROUP BY person_slug HAVING COUNT(*) >= 2
        )
        """
    )["n"]

    result = {"total_people": total_people, "people_on_multiple_projects": multi_project_people}
    for kind in KINDS:
        pairs = _pairs_for(kind)
        weights = [p["weight"] for p in pairs]
        result[kind] = {
            "pair_count": len(weights),
            "pairs_below_floor": sum(1 for w in weights if w < DEFAULT_MIN_WEIGHT[kind]),
            "max_weight": max(weights) if weights else 0,
        }
    return result


def neighbours(slug: str, kind: str, min_weight: int) -> list[dict]:
    """Every collaborator of ``slug`` for ``kind``, sorted by weight desc —
    the person-anchored neighbourhood view. Empty is a valid answer (someone
    whose only project had no co-listed person), not an error."""
    rows = []
    for pair in enriched_pairs(kind):
        if pair["weight"] < min_weight:
            continue
        if pair["person_a_slug"] == slug:
            other = "b"
        elif pair["person_b_slug"] == slug:
            other = "a"
        else:
            continue
        rows.append(
            {
                "slug": pair[f"person_{other}_slug"],
                "name": pair[f"person_{other}"],
                "groups": pair[f"person_{other}_groups"],
                "weight": pair["weight"],
                "weight_normalized": pair["weight_normalized"],
                "cross_group": pair["cross_group"],
            }
        )
    rows.sort(key=lambda r: (-r["weight"], r["name"]))
    return rows
