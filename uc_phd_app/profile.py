"""The interest profile the Fit screen matches against — load, validate, save.

Same front-matter + body shape as ``estudo_geral/*.md``, parsed the same way
``theses.py:_load_front_matters`` parses those, so there is one notion of "a
markdown file with YAML front matter" in this repo rather than two.

What is embedded, and what is not
----------------------------------
Only ``interests`` — a **list** of short interest lines, each embedded and
queried separately (``store.match_theses`` fuses them by max). The body prose
is displayed on screen as context and is deliberately **never** embedded.

That split is measured, not stylistic. Embedding the CV paragraph as one
vector ranks the human-factors theses 1-2-3 and pushes the privacy/security
architecture thesis out of the top 10, because half the paragraph is career
narrative and averaging four distinct interests into one 768-dim vector lands
the query near-equidistant from everything (top1-top5 spread 0.022 for the
paragraph against 0.081 for a facet). Split into four queries, 4 of the top 5
sit on his stated interests instead of 2. See the Architect's note on the
card, and ``store.match_theses``.

Seed vs live — the same split ``seed.py`` makes for ``cisuc.sqlite3``
---------------------------------------------------------------------
``profile/research_interests.md`` in the repo is a **versioned baseline**. The
package dir is deleted and re-fetched wholesale on every app update
(``paths.py``), so a profile the user edited in the UI would silently vanish at
the next version bump if it lived there. The live, editable copy therefore goes
in the data dir, and ``load()`` copies the seed across on first use with the
same ``mkstemp`` + ``os.replace`` dance ``seed.py:_atomic_copy`` uses — at
``AW_WORKSPACE_WORKERS>1`` every worker does this independently, and a naive
``shutil.copy`` racing itself yields a half-written file that ``yaml.safe_load``
either rejects or, worse, parses into a truncated interest list.

``save()`` lands the same way, for the same reason: a ``PUT /api/profile``
concurrent with a ``GET /api/fit`` in another worker must never let the reader
see a partially-written file.

Nothing is cached in module state. The parsed profile is re-read per call and
the *embedding* cache in ``store`` is keyed on a hash of the interest text, so
an edit by worker A is picked up by worker B without any cross-process
invalidation — see ``store.match_theses``.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import yaml  # requirements.txt — now installed by app-release.yml before tests

from . import paths

#: A profile with no interests cannot rank anything, and an empty list is a
#: user error worth naming rather than an empty screen.
MIN_INTERESTS = 1

#: Each interest is a short phrase, not an essay — the whole point of the
#: facet split is that one vector carries one idea. Generous enough not to
#: fight a legitimately wordy interest, tight enough that pasting the CV
#: paragraph into a single line fails loudly instead of silently recreating
#: the averaged-centroid behaviour the facet split exists to avoid.
MAX_INTEREST_CHARS = 300
MAX_INTERESTS = 20


class ProfileError(ValueError):
    """Invalid profile content — surfaced as a 400, never a 500."""


def _split_front_matter(raw: str) -> tuple[dict, str]:
    """``---\\n<yaml>\\n---\\n\\n<body>`` -> (front matter, body).

    Same delimiters ``theses.py`` expects of ``estudo_geral/*.md``; a file
    without them is a corrupt profile, not an empty one.
    """
    if not raw.startswith("---\n"):
        raise ProfileError("profile has no YAML front matter delimiters")
    end = raw.find("\n---\n", 4)
    if end == -1:
        raise ProfileError("profile front matter is not terminated")
    front = yaml.safe_load(raw[4:end]) or {}
    if not isinstance(front, dict):
        raise ProfileError("profile front matter is not a mapping")
    return front, raw[end + len("\n---\n"):].lstrip("\n")


def validate_interests(value: object) -> list[str]:
    """Normalise and check the ``interests`` list, raising ``ProfileError``
    with a message a user can act on."""
    if not isinstance(value, list):
        raise ProfileError("'interests' must be a list of interest lines")
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            raise ProfileError(f"interest {item!r} is not text")
        text = " ".join(item.split())
        if text:
            cleaned.append(text)
    if len(cleaned) < MIN_INTERESTS:
        raise ProfileError("a profile needs at least one interest to match against")
    if len(cleaned) > MAX_INTERESTS:
        raise ProfileError(f"too many interests (max {MAX_INTERESTS})")
    for text in cleaned:
        if len(text) > MAX_INTEREST_CHARS:
            raise ProfileError(
                f"interest is {len(text)} characters, over the {MAX_INTEREST_CHARS} "
                "limit — each line should be one focused interest, not a paragraph"
            )
    return cleaned


def parse(raw: str) -> dict:
    """``{interests, body, front_matter}`` from the file's text."""
    front, body = _split_front_matter(raw)
    return {
        "interests": validate_interests(front.get("interests")),
        "body": body.strip(),
        "front_matter": front,
    }


def render(interests: list[str], body: str, front_matter: dict | None = None) -> str:
    """The inverse of ``parse`` — what ``save()`` writes.

    Front-matter keys other than ``interests`` (``source``, ``seeded_from``)
    are carried through, so saving an edited interest list never silently
    drops the provenance the seed recorded.
    """
    front = dict(front_matter or {})
    front["interests"] = interests
    dumped = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n\n{body.strip()}\n"


def _atomic_write(text: str, dest: Path) -> None:
    """Land ``text`` on ``dest`` so no reader ever sees a partial file.

    Same shape as ``seed.py:_atomic_copy`` — mkstemp in the destination
    directory (so ``os.replace`` stays within one filesystem, where it is
    atomic) and replace.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), prefix=".profile-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():  # pragma: no cover - only on a failed write
            tmp.unlink(missing_ok=True)


def _atomic_copy(src: Path, dest: Path) -> None:
    """``seed.py:_atomic_copy``, for the profile seed."""
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), prefix=".profile-", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():  # pragma: no cover - only on a failed copy
            tmp.unlink(missing_ok=True)


def ensure_seeded() -> Path:
    """Make sure the live profile exists, copying the committed seed across on
    first use. Safe to call concurrently from every worker."""
    live = paths.live_profile_path()
    if not live.is_file():
        seed = paths.seed_profile_path()
        if not seed.is_file():
            raise ProfileError(f"no committed profile seed at {seed}")
        _atomic_copy(seed, live)
    return live


def seed_interests() -> list[str] | None:
    """The committed baseline's interests, or ``None`` if the seed is absent
    or unreadable. Used only to report divergence — never a reason to fail a
    request, since the live profile is what actually matters."""
    seed = paths.seed_profile_path()
    try:
        return parse(seed.read_text(encoding="utf-8"))["interests"]
    except (OSError, ProfileError, yaml.YAMLError):  # pragma: no cover - defensive
        return None


def load() -> dict:
    """The live profile, seeding it from the committed baseline if absent.

    Re-read on every call rather than cached in module state: at
    ``AW_WORKSPACE_WORKERS>1`` a ``PUT`` handled by one worker has to be
    visible to the next ``GET`` on another, and there is no cross-process
    invalidation channel here. The expensive part — embedding — is cached
    separately in ``store``, keyed on the interest text itself, so re-reading
    a small file per request costs nothing that matters.
    """
    live = ensure_seeded()
    data = parse(live.read_text(encoding="utf-8"))
    baseline = seed_interests()
    data["differs_from_seed"] = baseline is not None and baseline != data["interests"]
    data["seed_interests"] = baseline
    return data


def save(interests: object, body: str | None = None) -> dict:
    """Validate and persist an edited profile, returning the new ``load()``."""
    cleaned = validate_interests(interests)
    current = load()
    text = render(
        cleaned,
        current["body"] if body is None else body,
        current["front_matter"],
    )
    _atomic_write(text, paths.live_profile_path())
    return load()


def reset_to_seed() -> dict:
    """Throw the live profile away and restore the committed baseline — the
    counterpart to the "differs from the committed profile" flag."""
    seed = paths.seed_profile_path()
    if not seed.is_file():
        raise ProfileError(f"no committed profile seed at {seed}")
    _atomic_copy(seed, paths.live_profile_path())
    return load()
