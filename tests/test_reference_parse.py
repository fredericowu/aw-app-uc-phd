"""analysis/reference_parse.py — replayed against real corpus strings.

Every literal in this file was copied out of a real ``estudo_geral/*.md``,
the same way tests/test_name_match.py replays 50 hand-verified name
decisions. Invented examples would pass while the corpus kept failing: the
things that break this parser (a space inside a word, a running page header
that looks like a heading, a year that dates the journal instead of the
authors) are not things anyone writes by hand.
"""
from __future__ import annotations

import pytest

from analysis import reference_parse as rp

# The card's ground truth: DOI 10.1109/32.666826 (Carreira et al., Xception)
# cited by five theses, every one with a different string — different author
# order, an inverted journal name, and both corruption directions at once.
# Verbatim, non-breaking spaces and all.
XCEPTION = [
    "João Carreira, Henrique Madeira, and João Gabriel Silva. Xception: A technique "
    "for the experimental evaluation of dependability in modern computers. IEEE "
    "Transactions on Software Engineering, 24(2):125–136, 1998. ISSN 00985589. "
    "doi: 10.1109/32.666826.",
    "Carreira, J., H. Madeira, and J.G. Silva. 1998. “Xception: A Technique for the "
    "Experimental Evaluation of Depe ndability in Modern Computers.” IEEE "
    "Transactions on Software Engineering 24 (2): 125–36. doi:10.1109/32.666826.",
    "Carreira, \xa0J., \xa0H. \xa0Madeira, \xa0and \xa0J. \xa0G \xa0Silva. \xa01998. "
    "\xa0“Xception: \xa0a \xa0technique \xa0for \xa0 the \xa0 experimental \xa0evaluation "
    "\xa0 ofdependability \xa0 in \xa0 modern \xa0computers.” \xa0IEEE \xa0 Transactions "
    "\xa0 on \xa0 Software \xa0 Engineering \xa024 \xa0 (2) \xa0(February): "
    "\xa0125-\xad‐‑136. \xa0doi:10.1109/32.666826.",
]


# ── the heading is a seed, not a section ─────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        " References ",
        "Referências ",
        "BIBLIOGRAPHY",
        "Bibliografia",
        "220 Bibliografia ",  # running page header, number BEFORE
        "Bibliography 133",  # running page header, number AFTER
        "References:",
    ],
)
def test_marker_matches_every_heading_form_this_corpus_publishes(line):
    assert rp.MARKER.match(line)


@pytest.mark.parametrize(
    "line",
    [
        "REFERENCES .................................................",  # a TOC row
        "Figure 3.1 First (reference) and third images from each se-",
        "PA: Information Science Reference (IGI Global), December.",
        "terchangeably, although a preference will be given to the fo",
    ],
)
def test_marker_rejects_prose_and_table_of_contents_rows(line):
    assert not rp.MARKER.match(line)


def test_regions_merge_across_a_running_page_header():
    """The bug this exists to stop: a header mid-bibliography split one
    region into several and the entries in the gap were silently dropped —
    which is how a real ground-truth DOI went missing."""
    entry = "Zhang, Y. and J. Jiang (2001). Integrated active fault-tolerant control. IEEE, 37(4), 1221."
    lines = ["References"] + [entry] * 40 + ["220 Bibliografia"] + [entry] * 40
    regions = rp.marker_regions(lines)
    assert len(regions) == 1
    start, end = regions[0]
    assert end - start >= 78


def test_a_heading_with_nothing_reference_shaped_after_it_is_not_a_region():
    lines = ["References"] + ["see chapter four"] * 40
    assert rp.marker_regions(lines) == []


def test_tail_fallback_finds_a_bibliography_whose_heading_did_not_survive():
    """8 real theses in this corpus have body text, no usable heading, and a
    genuine bibliography at the tail."""
    entries = [
        f"Author{i}, A. B. (20{i:02d}). A study of something measurable. Journal of Things, 4(2), 11-20."
        for i in range(30)
    ]
    lines = ["chapter prose with no year or commas here"] * 40 + entries
    regions = rp.tail_regions(lines)
    assert len(regions) == 1
    style, parsed = rp.segment(lines[regions[0][0] : regions[0][1]])
    assert len(parsed) >= 25


def test_tail_fallback_does_not_mistake_a_list_of_figures_for_a_bibliography():
    """A TOC is dense in years and dots, which is exactly what makes this
    fallback dangerous if it runs unguarded."""
    lines = ["prose"] * 40 + [
        f"1.{i} Structure of this Thesis . . . . . . . . . . . . . {i}" for i in range(40)
    ]
    assert rp.tail_regions(lines) == []


def test_regions_prefers_the_heading_and_falls_back_only_when_there_is_none():
    entry = "Gamma, E. (1995). Design patterns: elements of reusable software. Addison-Wesley."
    with_heading = ["References"] + [entry] * 40
    assert rp.regions(with_heading) == rp.marker_regions(with_heading)


# ── segmentation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "style,lines",
    [
        (
            "bracketed",
            [
                "[1]  L. A. Meserve, “The Problem with Relying on Technol ogy,” The Ohio Journal of",
                "Science, vol. 98, nº 3, pp. 34-38, June 1998.",
                "[2]  N. Carr, The Glass Cage: How Our Computers Are Chan ging Us, W. W. Norton &",
                "Company, 2015.",
                "[3]  H. C. Jiau, J. C. Chen e K.-F. Ssu, “Enhancing Self-Motivation in Learning",
                "Programming Using Game-Based Simulation,” IEEE Transactions on Education, 2009.",
            ],
        ),
        (
            "labelled",
            [
                "[Ward et al., 1999] Ward, T., Smith, S., and Finke, R. (1999). Creative Cognition.",
                "Handbook of Creativity , pag. 189–213.",
                "[Weisberg, 1999] Weisberg, R. (1999). Creativity and knowledge: a challenge.",
                "Handbook of Creativity , pag. 226–251.",
                "[Wiggins, 2001] Wiggins, G. A. (2001). Towards a more precise charaterization of",
                "creativity in AI. In Cardoso, A., editors, Proceedings of the First Workshop.",
            ],
        ),
        (
            "authoryear",
            [
                "Zhang, Y. and J. Jiang (1999b). An intera cting multiple-model based fault detection",
                "diagnosis approach. Proc. of the 38 th IEEE Conference on Decision and Control.",
                "Zhang, Y. and J. Jiang (2000). Design of pr oportional-integral rec onfigurable control",
                "systems via eigenstructure assignment. Proc. of the American Control Conference.",
                "Zhang, Y. and J. Jiang (2001). Integrated active fault-tolerant control using IMM.",
                "IEEE Transactions on Aerospace and Electronic Systems, 37(4), 1221-1235.",
            ],
        ),
    ],
)
def test_segment_recognises_each_style_this_corpus_uses(style, lines):
    found, entries = rp.segment(lines)
    assert found == style
    assert len(entries) == 3


def test_segment_joins_an_entrys_continuation_lines_into_one_string():
    lines = [
        "[1]  L. A. Meserve, “The Problem with Relying on Technol ogy,” The Ohio Journal of",
        "Science, vol. 98, nº 3, pp. 34-38, June 1998.",
        "[2]  N. Carr, The Glass Cage, W. W. Norton & Company, 2015. A second line here too.",
        "[3]  H. Jiau, “Enhancing Self-Motivation in Learning Programming,” IEEE Trans, 2009.",
    ]
    _, entries = rp.segment(lines)
    assert "The Ohio Journal of Science" in entries[0]


def test_segment_returns_nothing_rather_than_guessing_on_unparseable_text():
    assert rp.segment(["prose", "more prose", "and more"]) == ("none", [])


# ── field extraction ─────────────────────────────────────────────────────


def test_title_comes_from_the_quoted_span_when_there_is_one():
    title = rp.extract_title(
        '[1]  L. A. Meserve, “The Problem with Relying on Technol ogy,” The Ohio Journal, 1998.'
    )
    assert title == "The Problem with Relying on Technol ogy"


def test_a_year_in_the_first_half_dates_the_authors_so_the_title_follows_it():
    title = rp.extract_title(
        "Zhang, Y. and J. Jiang (2001). Integrated active fault-tolerant control using IMM "
        "approach. IEEE Transactions on Aerospace and Electronic Systems, 37(4), 1221-1235."
    )
    assert title == "Integrated active fault-tolerant control using IMM approach"


def test_a_year_in_the_tail_belongs_to_the_journal_so_the_title_precedes_it():
    """Getting this backwards yields "ISSN 00985589. doi: ..." as the title,
    which then hashes to a key that can never match anything. It cost this
    parser two of the five ground-truth theses before it was fixed."""
    assert rp.extract_title(XCEPTION[0]) == (
        "Xception: A technique for the experimental evaluation of dependability in modern computers"
    )


def test_first_author_skips_leading_initials():
    assert rp.extract_first_author('[1] L. A. Meserve, “The Problem,” Ohio, 1998.') == "Meserve"


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("Zhang, Y. and J. Jiang (2001). Integrated control.", "Zhang"),
        ("João Carreira, Henrique Madeira, and João Silva. Xception. IEEE, 1998.", "Carreira"),
        ("[Ward et al., 1999] Ward, T., Smith, S. (1999). Creative Cognition.", "Ward"),
        ("Bibliography only, nothing else", "Bibliography"),
    ],
)
def test_first_author_handles_every_author_shape(entry, expected):
    assert rp.extract_first_author(entry) == expected


def test_first_author_is_none_when_the_entry_does_not_start_with_a_name():
    assert rp.extract_first_author("123 numbers only") is None


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("Zhang, Y. (2001). Integrated control. IEEE.", "2001"),
        ("Carreira, J. 1998. “Xception.” IEEE TSE.", "1998"),
        ("Some entry mentioning 1843 with no punctuation after", "1843"),
    ],
)
def test_year_extraction(entry, expected):
    assert rp.extract_year(entry) == expected


def test_year_is_none_when_there_is_none():
    assert rp.extract_year("No date anywhere in this string.") is None


def test_title_is_none_when_nothing_title_shaped_is_present():
    assert rp.extract_title("Short.") is None


# ── normalisation, the thing the whole design turns on ───────────────────


def test_normalise_collapses_all_three_corruption_kinds_to_one_string():
    """Spurious space, missing space, and '#' for space — one file in this
    corpus substitutes '#' for every single space. A token-based
    normalisation treats all three as different strings."""
    assert (
        rp.normalise("Technol ogy")
        == rp.normalise("Technology")
        == rp.normalise("Technol#ogy")
        == "technology"
    )


def test_normalise_strips_diacritics_and_punctuation():
    assert rp.normalise("Referências, Ação — 2001!") == "referenciasacao2001"


def test_normalise_treats_none_as_empty():
    assert rp.normalise(None) == ""


def test_every_corrupted_xception_string_reduces_to_one_key():
    """The measured claim the two-tier design rests on, pinned. These three
    strings share no byte-level run — different author order, an inverted
    journal name, and both corruption directions."""
    keys = {rp.normalised_key(e) for e in XCEPTION}
    assert len(keys) == 1
    assert keys.pop().startswith("carreira|xception")


def test_normalised_key_is_none_when_no_title_can_be_located():
    """A reference with no usable key is stored as a singleton, never folded
    into a group it might not belong to."""
    assert rp.normalised_key("Ibid.") is None


def test_normalised_key_rejects_a_title_too_short_to_discriminate():
    assert rp.normalised_key("Smith, J. (2001). Ada. Press.") is None


# ── DOI hygiene ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["10.1016/j", "10.1007/978-", "10.1109/32.", "10.1234/ab"])
def test_clean_doi_rejects_a_line_wrapped_doi(raw):
    assert rp.clean_doi(raw) is None


def test_clean_doi_strips_the_trailing_sentence_punctuation():
    assert rp.clean_doi("10.1109/32.666826.") == "10.1109/32.666826"
    assert rp.clean_doi("10.1109/32.666826)") == "10.1109/32.666826"


def test_clean_doi_lowercases_so_two_casings_are_one_doi():
    assert rp.clean_doi("10.1109/32.666826") == rp.clean_doi("10.1109/32.666826".upper())


def test_drop_truncated_rejects_a_prefix_of_another_observed_doi():
    """clean_doi cannot see this one: "10.1145/1965724" is well-formed alone
    and only reveals itself once the full DOI is also in the corpus. 74 of
    this corpus's DOIs fail here, and they were grouping unrelated theses."""
    kept = rp.drop_truncated({"10.1145/1965724", "10.1145/1965724.1965742", "10.1000/xyz123"})
    assert kept == {"10.1145/1965724.1965742", "10.1000/xyz123"}


def test_drop_truncated_keeps_dois_that_merely_share_a_registrant():
    kept = rp.drop_truncated({"10.1109/32.666826", "10.1109/32.666827"})
    assert len(kept) == 2


# ── display ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("[138] Alex Krizhevsky. ImageNet, 2012.", "Alex Krizhevsky. ImageNet, 2012."),
        ("[Gamma 94] Erich Gamma. Design patterns.", "Erich Gamma. Design patterns."),
        ("12. Tranfield, D. Towards a methodology, 2003.", "Tranfield, D. Towards a methodology, 2003."),
    ],
)
def test_display_form_drops_the_leading_style_marker(entry, expected):
    assert rp.display_form(entry) == expected


def test_display_form_collapses_pdf_whitespace_runs():
    assert rp.display_form("Gamma,   Erich,   Richard   Helm") == "Gamma, Erich, Richard Helm"


def test_display_form_does_not_repair_corruption_inside_a_word():
    """Guessing where a space does not belong is inventing text a reader
    would take for the source. The key absorbs it; the display does not."""
    assert "Technol ogy" in rp.display_form("[1] A. B. “Technol ogy,” 1998.")


def test_body_of_requires_front_matter():
    with pytest.raises(ValueError, match="front matter"):
        rp.body_of("no front matter here")


def test_parse_document_reads_a_whole_thesis_file():
    entries = [
        f"Author{i}, A. B. (20{i:02d}). A study of something measurable. Journal of Things, 4(2), 11-20."
        for i in range(30)
    ]
    text = "---\nhandle: 10316/1\nfull_text: true\n---\n\n# Title\n\nReferences\n" + "\n".join(entries)
    parsed = rp.parse_document(text)
    assert len(parsed) >= 25
    assert all("A study of something measurable" in e for e in parsed)
