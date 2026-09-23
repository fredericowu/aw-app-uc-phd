"""Pull bibliographic references out of a PDF-extracted thesis body.

Pure functions, no database — the sibling of ``analysis/name_match.py``, and
split out of ``analysis/build_bibliography.py`` for the same reason: the
decisions here are the ones worth replaying against real examples in a test,
and a builder that owns a connection is not replayable.

What the input actually looks like
----------------------------------
``estudo_geral/*.md`` is raw PDF text dumped under a single ``# title``. There
are **no markdown headings** for a references section — the heading, when it
survived at all, is a plain text line. Three things follow, and every one of
them is a measured property of this corpus, not a guess:

* **A heading line is a seed, not a section.** 67 of the files repeat their
  heading as a running page header on every page of the bibliography, and
  ``10316-10153`` publishes it as ``220 Bibliografia``. Treating each hit as a
  section start yields up to 49 "sections" in one thesis. So a hit only
  *seeds* a region whose real extent is decided by entry-shape density, and
  regions separated by a small gap are merged back together — a page header or
  a figure block splits one bibliography into several otherwise.
* **Thesis-by-publication is the norm, not the exception.** Files carry more
  than one genuine references section, one per embedded paper. Every region is
  parsed; taking the first or the last loses most of the entries.
* **Extraction corrupts words in both directions.** Spaces appear inside words
  ("Technol ogy", "Depe ndability"), disappear between them ("ofdependability"),
  and ``10316-25654`` has every space replaced by ``#``. ``normalised_key``
  answers all three at once by removing whitespace *and* punctuation entirely
  (see ``MATCHER_VERSION``), which no token-based normalisation does.

What this module does NOT claim
-------------------------------
Entry segmentation is heuristic and its failures are real, not theoretical:
measured against DOI ground truth, two theses citing the same work produce the
same ``normalised_key`` **52.6%** of the time (30 of 57 shared-DOI groups —
``analysis/build_bibliography.py`` recomputes this on every run and prints it).
The remainder are mostly entry-boundary errors, where a title span picks up the
tail of the neighbouring entry. That is why ``match_tier`` is a stored column
and why the UI states the figure: a reference counted once here may genuinely
be cited twice.

A note on grep
--------------
21 of the 181 files contain NUL bytes, so ``grep`` classifies them as binary
and silently prints nothing for them. Any count of this corpus taken with
``grep`` is an undercount by up to 21 files unless it passes ``-a``. Three
separate "anomalies" in this feature's design notes turned out to be that one
cause; read a file in Python before concluding a heading is missing from it.
"""
from __future__ import annotations

import re
import statistics
import unicodedata

#: Bump when any rule below changes the key a reference hashes to. The key is
#: frozen into the committed seed, so a matcher improvement only reaches a
#: workspace through a rebuilt seed and a version bump — the column exists so
#: that a seed built by an older matcher is recognisable rather than silently
#: mixed with a newer one. See ``uc_phd_app/seed.py``'s upgrade rule.
MATCHER_VERSION = 1

#: A references heading, alone on its line. The optional leading and trailing
#: integers are the running page numbers this corpus prints around it.
MARKER = re.compile(
    r"^\s*(?:\d{1,4}\s*[\.\)]?\s*)?"
    r"(references|reference list|bibliography|bibliographie|bibliografia"
    r"|bibliograf[ií]a|refer[êe]ncias|referencias|literature cited|works cited)"
    r"\s*[:\.]?\s*(?:\d{1,4})?\s*$",
    re.IGNORECASE,
)

YEAR = re.compile(r"(?:1[89]|20)\d{2}")
DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;\"'<>()\[\]]{4,}", re.IGNORECASE)

#: The shapes an entry's first line takes in this corpus. Each is tried over
#: every region and scored (see ``_score``) — the corpus holds at least five
#: styles and a thesis does not announce which one it used.
ENTRY_STARTS = {
    # "1. Author, ..." / "12) Author, ..."      (IEEE numbered)
    "numbered": re.compile(r"^\s*\d{1,3}\s*[\.\)]\s+\S"),
    # "[1] Author, ..."                          (IEEE bracketed)
    "bracketed": re.compile(r"^\s*\[\s*\d{1,3}\s*\]\s*\S"),
    # "[Ward et al., 1999] Ward, T., ..."        (labelled / alpha keys)
    "labelled": re.compile(r"^\s*\[[^\]\d][^\]]{2,60}\]\s*\S"),
    # "Zhang, Y. and J. Jiang (2001)." / "Zhang (2001)"   (Harvard/IFAC)
    "authoryear": re.compile(
        r"^\s*[A-ZÀ-Þ][\w'’\-]+\s*,\s*(?:[A-ZÀ-Þ]\.|[A-ZÀ-Þ][\w'’\-]+)"
        r"|^\s*[A-ZÀ-Þ][\w'’\-]+\s*\((?:1[89]|20)\d{2}"
    ),
    # "João Carreira, Henrique Madeira, and ..."  (given names written out)
    "authorfull": re.compile(r"^\s*(?:[A-ZÀ-Þ][\w'’\-]+\.?\s+){1,3}[A-ZÀ-Þ][\w'’\-]+\s*,\s"),
}

#: Sliding window, in lines, that entry-shape density is measured over.
WINDOW = 16
#: Two regions closer than this are one bibliography interrupted by a page
#: header or a figure block, not two sections.
MERGE_GAP = 60
#: Density a window must hold to keep a region growing.
DENSITY_FLOOR = 0.45
#: A heading-less tail region needs at least this many entry starts before it
#: is believed. Low enough to catch a short bibliography, high enough that a
#: list of figures or a table of contents never clears it.
MIN_TAIL_ENTRIES = 20

_QUOTED = re.compile(r"[“\"«‘]([^”\"»’]{15,300})[”\"»’]")
_YEAR_PAREN = re.compile(r"\(\s*((?:1[89]|20)\d{2})\s*[a-z]?\s*\)")
_YEAR_BARE = re.compile(r"(?<![\d/(])\b((?:1[89]|20)\d{2})[a-z]?\s*[\.,]")
#: A sentence boundary: a period followed by whitespace and a capital.
_SENTENCE = re.compile(r"\.\s+(?=[A-ZÀ-Þ]|In\b|$)")
_LABEL = re.compile(r"^\s*(?:\[[^\]]{1,60}\]|\d{1,3}\s*[\.\)])\s*")
_LEADING_INITIALS = re.compile(r"^\s*(?:[A-ZÀ-Þ]\.\s*)+")


def body_of(text: str) -> str:
    """The document body — everything after the YAML front matter."""
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("no YAML front matter delimiters found")
    return parts[2]


def _entry_shaped(line: str) -> bool:
    """Could this line be part of a reference entry? Deliberately loose — it
    is a density signal over a window, never a per-line verdict."""
    s = line.strip()
    return len(s) >= 12 and (bool(YEAR.search(s)) or bool(DOI.search(s)) or s.count(",") >= 2)


def density(lines: list[str]) -> float:
    """Fraction of non-blank lines that look like reference text. Blank lines
    are ignored rather than counted against: several styles put a blank line
    between every entry, and counting them would halve the density of exactly
    the regions this is meant to find."""
    real = [line for line in lines if line.strip()]
    return sum(map(_entry_shaped, real)) / len(real) if real else 0.0


def _grow(lines: list[str], start: int) -> int:
    """Extend a region forward while entry-density holds.

    A single low window does not end the region — a page break or a figure
    caption dips below the floor mid-bibliography, so a three-window lookahead
    has to agree before the region is closed.
    """
    i, n = start, len(lines)
    while i < n:
        if density(lines[i : i + WINDOW]) < DENSITY_FLOOR:
            if density(lines[i : i + WINDOW * 3]) < DENSITY_FLOOR:
                break
        i += WINDOW
    return min(i, n)


def marker_regions(lines: list[str]) -> list[tuple[int, int]]:
    """``[start, end)`` line ranges seeded by a references heading."""
    raw: list[tuple[int, int]] = []
    for hit in (i for i, line in enumerate(lines) if MARKER.match(line)):
        if raw and hit <= raw[-1][1]:
            continue  # a running header inside a region we already hold
        end = _grow(lines, hit + 1)
        if end - hit >= 5:
            raw.append((hit + 1, end))
    merged: list[tuple[int, int]] = []
    for start, end in raw:
        if merged and start - merged[-1][1] <= MERGE_GAP:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def tail_regions(lines: list[str]) -> list[tuple[int, int]]:
    """Fallback for a thesis whose references heading did not survive
    extraction: the longest run of consistently-shaped entry starts in the
    document tail.

    Only consulted when ``marker_regions`` found nothing, and only over the
    last 45% of the document — run unconditionally it would also "find" a
    list of figures or a table of contents, both of which are dense in years
    and commas. Recovers 8 real bibliographies in this corpus.
    """
    n = len(lines)
    start = int(n * 0.55)
    best: tuple[float, int, int] | None = None
    for pattern in ENTRY_STARTS.values():
        idx = [i for i in range(start, n) if pattern.match(lines[i])]
        if len(idx) < MIN_TAIL_ENTRIES:
            continue
        runs, current = [], [idx[0]]
        for a, b in zip(idx, idx[1:]):
            if b - a <= 12:
                current.append(b)
            else:
                runs.append(current)
                current = [b]
        runs.append(current)
        run = max(runs, key=len)
        if len(run) < MIN_TAIL_ENTRIES:
            continue
        a, b = run[0], min(run[-1] + 12, n)
        score, _ = _score(
            _split(lines[a:b], [i - a for i in run]),
            sum(len(line.strip()) for line in lines[a:b] if line.strip()),
        )
        if score > 0.25 and (best is None or score > best[0]):
            best = (score, a, b)
    return [(best[1], best[2])] if best else []


def regions(lines: list[str]) -> list[tuple[int, int]]:
    """Every reference region in one document, heading-seeded or tail-found."""
    return marker_regions(lines) or tail_regions(lines)


def _split(lines: list[str], starts: list[int]) -> list[str]:
    """Join each start line to the continuation lines that follow it."""
    out = []
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        out.append(" ".join(x.strip() for x in lines[a:b] if x.strip()))
    return out


def _score(candidates: list[str], region_chars: int) -> tuple[float, list[str]]:
    """How well does one segmentation explain the region?

    ``coverage * plausibility``, because neither alone separates the two ways
    this goes wrong. Counting entries rewards over-splitting (every fragment
    is another "entry"); coverage alone rewards under-splitting (one giant
    entry covers everything). Over-splitting loses plausibility — the
    fragments stop carrying a year — and under-splitting loses coverage once
    the length cap rejects the giant. ``shape`` then penalises a median entry
    length outside what a bibliographic reference plausibly is.
    """
    good = [e for e in candidates if 40 <= len(e) <= 1500 and YEAR.search(e)]
    if len(good) < 3:
        return 0.0, good
    coverage = min(sum(len(e) for e in good) / max(region_chars, 1), 1.0)
    plausibility = len(good) / max(len(candidates), 1)
    median = statistics.median(len(e) for e in good)
    shape = 1.0 if 60 <= median <= 600 else 0.4
    return coverage * plausibility * shape, good


def segment(lines: list[str]) -> tuple[str, list[str]]:
    """Split one region into entries. Returns ``(style, entries)``.

    Every style in ``ENTRY_STARTS`` is tried, plus blank-line delimiting, and
    the best-scoring one wins. Trying them all rather than detecting the style
    up front is deliberate: a thesis-by-publication mixes styles between its
    embedded papers, and per-region scoring picks the right one for each.
    """
    region_chars = sum(len(line.strip()) for line in lines if line.strip())
    best: tuple[str, list[str], float] = ("none", [], 0.0)
    for name, pattern in ENTRY_STARTS.items():
        idx = [i for i, line in enumerate(lines) if pattern.match(line)]
        if len(idx) < 3:
            continue
        score, good = _score(_split(lines, idx), region_chars)
        if score > best[2]:
            best = (name, good, score)
    blocks, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    score, good = _score(blocks, region_chars)
    if score > best[2]:
        best = ("blankline", good, score)
    return best[0], best[1]


def parse_document(text: str) -> list[str]:
    """Every reference entry in one thesis ``.md``, in document order."""
    lines = body_of(text).splitlines()
    return [entry for a, b in regions(lines) for entry in segment(lines[a:b])[1]]


# ── field extraction ─────────────────────────────────────────────────────


def _strip_label(entry: str) -> str:
    return _LABEL.sub("", entry).strip()


def extract_title(entry: str) -> str | None:
    """Best-effort title span.

    A quoted run wins outright — IEEE, Chicago and the Portuguese variants all
    quote the title, and nothing else in an entry is quoted. Failing that the
    year locates it, and *where* the year sits decides which side of it to
    read: a year in the first half dates the authors ("Zhang, Y. (2001).
    Title."), so the title follows it; a year in the tail belongs to the
    journal citation ("Authors. Title. Journal, 24(2):125-136, 1998."), so the
    title is the segment after the author list instead. Getting that backwards
    silently yields "ISSN 00985589. doi: ..." as a title, which then hashes to
    a key that can never match anything.
    """
    body = _strip_label(entry)
    quoted = _QUOTED.search(body)
    if quoted:
        return quoted.group(1).strip(" ,.;")
    for pattern in (_YEAR_PAREN, _YEAR_BARE):
        match = pattern.search(body)
        if not match:
            continue
        if match.start() > len(body) * 0.55:
            break
        rest = body[match.end() :].lstrip(" .,:")
        cut = _SENTENCE.search(rest)
        title = (rest[: cut.start()] if cut else rest).strip(" ,.;")
        if 15 <= len(title) <= 400:
            return title
    for segment_ in _SENTENCE.split(body)[1:]:
        segment_ = segment_.strip(" ,.;")
        if 15 <= len(segment_) <= 400:
            return segment_
    return None


def extract_year(entry: str) -> str | None:
    """The publication year — parenthesised or bare, whichever comes first."""
    body = _strip_label(entry)
    for pattern in (_YEAR_PAREN, _YEAR_BARE):
        match = pattern.search(body)
        if match:
            return match.group(1)
    match = YEAR.search(body)
    return match.group(0) if match else None


def extract_first_author(entry: str) -> str | None:
    """The leading surname.

    Three shapes, tried in order: "Surname, I." (the overwhelming majority),
    "Firstname Surname," (given names written out), and a bare leading word as
    the last resort. Leading initials are stripped first — "L. A. Meserve,"
    would otherwise answer "L".
    """
    body = _LEADING_INITIALS.sub("", _strip_label(entry))
    surname = re.match(r"\s*([A-ZÀ-Þ][\w'’\-]+)\s*,", body)
    if surname:
        return surname.group(1)
    written_out = re.match(r"\s*(?:[A-ZÀ-Þ][\w'’\-]+\.?\s+){1,3}([A-ZÀ-Þ][\w'’\-]+)\s*[,\.&]", body)
    if written_out:
        return written_out.group(1)
    bare = re.match(r"\s*([A-ZÀ-Þ][\w'’\-]+)", body)
    return bare.group(1) if bare else None


def normalise(text: str | None) -> str:
    """NFKD, strip combining marks, lowercase, then remove **everything** that
    is not ``[a-z0-9]``.

    Removing whitespace as well as punctuation is the whole point, not an
    aesthetic choice: this corpus corrupts word boundaries in both directions
    ("Technol ogy" and "ofdependability" in the same sentence) and one file
    substitutes ``#`` for every space. A token-based normalisation treats
    those as different strings; this one collapses all of them, which is what
    lets the five differently-corrupted copies of the Xception title reduce to
    a single key.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def clean_doi(raw: str) -> str | None:
    """A DOI with trailing punctuation removed, or None if it looks truncated.

    Line-wrapping in the source PDF cuts DOIs mid-suffix ("10.1016/j",
    "10.1007/978-"), and a truncated DOI is the worst possible match key: it
    is high-confidence by construction and groups unrelated works. A suffix
    shorter than 4 characters or ending on a separator is rejected here;
    ``drop_truncated`` catches the rest, which needs the whole corpus.
    """
    doi = raw.rstrip(".,;:)]}’”").lower()
    suffix = doi.split("/", 1)[1] if "/" in doi else ""
    if len(suffix) < 4 or doi[-1] in "-./_":
        return None
    return doi


def drop_truncated(dois: set[str]) -> set[str]:
    """Reject every DOI that is a strict prefix of another observed one.

    ``clean_doi`` cannot see this: "10.1145/1965724" is well-formed on its own
    and only reveals itself as a line-wrap artefact once
    "10.1145/1965724.1965742" is also in the corpus. 74 of the DOIs in this
    corpus fail here, and they were grouping unrelated theses before.
    """
    ordered = sorted(dois, key=len)
    keep = set()
    for i, doi in enumerate(ordered):
        if any(other.startswith(doi) for other in ordered[i + 1 :]):
            continue
        keep.add(doi)
    return keep


def display_form(entry: str) -> str:
    """The entry as a reader should see it.

    Two changes, both presentational and both reversible from
    ``thesis_references.entry_raw``, which stays verbatim: the leading
    style marker is dropped (``[138]``, ``[Gamma 94]``, ``12.`` — it numbers
    that thesis's own list and means nothing once the work is shown on its
    own), and runs of whitespace are collapsed to one space (PDF extraction
    leaves non-breaking-space runs that render as ragged gaps).

    Deliberately does NOT try to repair corruption inside words. "Technol ogy"
    stays "Technol ogy": guessing where a space does not belong is inventing
    text, and this repo does not do that where a reader would take it for the
    source. The normalised key already absorbs it for matching purposes.
    """
    return re.sub(r"\s+", " ", _strip_label(entry)).strip()


def normalised_key(entry: str) -> str | None:
    """Tier-2 identity: ``<normalised first author>|<normalised title>``.

    None when no title could be located or the normalised title is too short
    to be discriminating — a reference with no usable key is stored with
    ``match_tier='unmatched'`` and counted once, never folded into a group it
    might not belong to.
    """
    title = normalise(extract_title(entry))
    if len(title) < 12:
        return None
    return f"{normalise(extract_first_author(entry))}|{title}"
