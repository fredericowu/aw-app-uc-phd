"""S1's extracted theses (``estudo_geral/*.md``) joined to CISUC research
groups via the S5 hand-verified attribution table.

Estudo Geral has no research-group field, and its CISUC community holds zero
theses (theses deposit under the department, not the research centre) — see
``docs/thesis-attribution.md``. So a thesis's group comes from joining its
author/supervisor names against the existing ``people`` table, then reading
that matched person's own project history for their group(s). The name ->
person identity join is the part that cannot be safely automated at this
scale, so it was hand-verified once and recorded in
``docs/thesis-attribution.json``; nothing here re-derives or guesses it. The
person -> group step *is* re-derived live, on every request, from the same
``project_people`` / ``project_groups`` tables every other figure in this app
already reads — a group is a live fact about a person's project history, not
something to freeze in the attribution file.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from . import db, paths

#: Carried with the theses payload — the per-thesis group list is
#: many-to-many for the same reason projects are (see
#: ``api/projects.py:GROUP_MANY_TO_MANY_CAVEAT``), compounded by supervisors
#: whose own coordinator-role projects already span several groups. See
#: ``docs/thesis-attribution.md`` for the full explanation.
GROUP_CAVEAT = (
    "A thesis's research group(s) is the union of its matched author's and "
    "supervisors' own groups, so a thesis can show more than one group — "
    "these counts sum to more than 18. A name with no exact match is never "
    "guessed; see docs/thesis-attribution.md for the full record."
)

ATTRIBUTION_NOTE = (
    "Group attribution is a hand-verified join of each thesis's author/"
    "supervisor names against the existing people/project_groups tables — "
    "Estudo Geral itself has no research-group field. Exact matching only "
    "(surname + given name or a standard initial); a name that does not "
    "exactly resolve is left unattributed rather than guessed. Full "
    "record: docs/thesis-attribution.md."
)


def _load_front_matters(estudo_geral_dir: Path | None = None) -> list[dict]:
    """Every thesis's YAML front matter, without reading the (much larger)
    body text that follows it."""
    directory = estudo_geral_dir or paths.estudo_geral_dir()
    front_matters = []
    for md_path in sorted(directory.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            raise ValueError(f"{md_path}: no YAML front matter delimiters found")
        front_matters.append(yaml.safe_load(parts[1]))
    return front_matters


def _load_attribution(attribution_path: Path | None = None) -> dict:
    path = attribution_path or paths.thesis_attribution_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_COORDINATOR_GROUPS_SQL = """
    SELECT DISTINCT pg.group_code
    FROM project_people pp JOIN project_groups pg ON pg.project_id = pp.project_id
    WHERE pp.person_slug = :slug AND pp.role = 'coordinator'
"""
_RESEARCHER_GROUPS_SQL = """
    SELECT DISTINCT pg.group_code
    FROM project_people pp JOIN project_groups pg ON pg.project_id = pp.project_id
    WHERE pp.person_slug = :slug AND pp.role = 'researcher'
"""


def _person_groups(slug: str, db_path: Path | None = None) -> set[str]:
    """A person's research group(s): their own coordinator-role projects if
    they have any (the strongest signal — see docs/thesis-attribution.md),
    else the groups of projects where they are listed as a researcher."""
    coordinator_groups = {
        r["group_code"] for r in db.rows(_COORDINATOR_GROUPS_SQL, {"slug": slug}, db_path)
    }
    if coordinator_groups:
        return coordinator_groups
    return {r["group_code"] for r in db.rows(_RESEARCHER_GROUPS_SQL, {"slug": slug}, db_path)}


def _resolve_name(name: str, attribution: dict, db_path: Path | None = None) -> dict:
    entry = attribution.get(name)
    if not entry or entry.get("status") != "matched":
        return {
            "name": name,
            "status": "unattributed",
            "note": (entry or {}).get("note"),
            "matched": [],
            "groups": [],
        }
    matched = []
    groups: set[str] = set()
    for m in entry["matches"]:
        matched.append(m)
        groups |= _person_groups(m["slug"], db_path)
    return {
        "name": name,
        "status": "matched",
        "note": entry.get("note"),
        "matched": matched,
        "groups": sorted(groups),
    }


def _thesis_summary(front_matter: dict, attribution: dict, db_path: Path | None = None) -> dict:
    authors = [_resolve_name(n, attribution, db_path) for n in front_matter.get("authors") or []]
    supervisors = [
        _resolve_name(n, attribution, db_path) for n in front_matter.get("supervisors") or []
    ]
    groups: set[str] = set()
    for resolved in (*authors, *supervisors):
        groups.update(resolved["groups"])
    date = front_matter.get("date") or ""
    return {
        "handle": front_matter["handle"],
        "title": front_matter["title"],
        "source_url": front_matter.get("source_url"),
        "year": date[:4] or None,
        "rights": front_matter.get("rights"),
        "full_text": bool(front_matter.get("full_text")),
        "authors": authors,
        "supervisors": supervisors,
        "groups": sorted(groups),
        "attributed": bool(groups),
    }


def list_theses(
    *,
    estudo_geral_dir: Path | None = None,
    attribution_path: Path | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Every thesis, with its author/supervisors resolved to a CISUC person
    (or flagged unattributed) and its research group(s) joined in live."""
    attribution = _load_attribution(attribution_path)
    return [
        _thesis_summary(fm, attribution, db_path)
        for fm in _load_front_matters(estudo_geral_dir)
    ]


def group_breakdown(theses: list[dict]) -> dict:
    """Per-group thesis counts (many-to-many, see ``GROUP_CAVEAT``) plus how
    many theses resolved to no group at all."""
    counts: dict[str, int] = {}
    unattributed = 0
    for thesis in theses:
        if not thesis["groups"]:
            unattributed += 1
            continue
        for code in thesis["groups"]:
            counts[code] = counts.get(code, 0) + 1
    return {"counts": counts, "unattributed": unattributed}
