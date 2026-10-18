"""Fixture-based tests for estudo_geral_extractor's pure functions.

Same convention as tests/test_parse.py and tests/test_detail_parser.py:
only parsing/selection logic is tested here, never the live HTTP paths
(oai.fetch_all_records, restapi.fetch_item, download.fetch_item_page/
download_pdf) — see pyproject.toml's coverage-gate comment for why.
"""
from xml.etree import ElementTree as ET

import pytest

from estudo_geral_extractor.download import find_download_link
from estudo_geral_extractor.markdown import (
    build_front_matter,
    handle_to_slug,
    render_markdown,
    rewrite_front_matter,
)
from estudo_geral_extractor.oai import HARVEST_SETS, parse_record, select_dei_doctoral_theses
from estudo_geral_extractor.restapi import parse_item_metadata
from estudo_geral_extractor.run import (
    carried_forward_entry,
    merge_by_handle,
    read_md_verbatim,
    write_md_verbatim,
)

OAI_RECORD_XML = """
<record xmlns="http://www.openarchives.org/OAI/2.0/">
  <header>
    <identifier>oai:estudogeral.uc.pt:10316/119257</identifier>
    <datestamp>2025-06-03T22:07:48Z</datestamp>
    <setSpec>com_10316_15517</setSpec>
    <setSpec>com_10316_255</setSpec>
    <setSpec>com_10316_27713</setSpec>
    <setSpec>col_10316_15519</setSpec>
  </header>
  <metadata>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
                xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:type>info:eu-repo/semantics/doctoralThesis</dc:type>
      <dc:date>2025-04-24</dc:date>
    </oai_dc:dc>
  </metadata>
</record>
"""

OAI_DELETED_RECORD_XML = """
<record xmlns="http://www.openarchives.org/OAI/2.0/">
  <header status="deleted">
    <identifier>oai:estudogeral.uc.pt:10316/1</identifier>
    <datestamp>2025-01-01T00:00:00Z</datestamp>
  </header>
</record>
"""


def test_parse_record_extracts_handle_types_dates():
    el = ET.fromstring(OAI_RECORD_XML)
    r = parse_record(el)
    assert r["handle"] == "10316/119257"
    assert r["deleted"] is False
    assert r["types"] == ["info:eu-repo/semantics/doctoralThesis"]
    assert r["dates"] == ["2025-04-24"]


def test_parse_record_captures_the_whole_setspec_list_in_header_order():
    """Origin is multi-valued and arrives for free: the header reports every
    community AND collection the item belongs to, including the UC-wide
    umbrella we never enumerate, whichever set we reached it through."""
    r = parse_record(ET.fromstring(OAI_RECORD_XML))
    assert r["set_specs"] == [
        "com_10316_15517",
        "com_10316_255",
        "com_10316_27713",
        "col_10316_15519",
    ]


def test_parse_record_deleted_has_no_metadata():
    el = ET.fromstring(OAI_DELETED_RECORD_XML)
    r = parse_record(el)
    assert r["deleted"] is True
    assert r["types"] == []
    assert r["dates"] == []
    assert r["set_specs"] == []


def test_select_filters_type_and_deleted_no_year_floor():
    records = [
        {"handle": "a", "deleted": False, "types": ["info:eu-repo/semantics/doctoralThesis"], "dates": ["2025-01-01"]},
        {"handle": "b", "deleted": False, "types": ["info:eu-repo/semantics/doctoralThesis"], "dates": ["2023-01-01"]},
        {"handle": "c", "deleted": False, "types": ["info:eu-repo/semantics/masterThesis"], "dates": ["2025-01-01"]},
        {"handle": "d", "deleted": True, "types": ["info:eu-repo/semantics/doctoralThesis"], "dates": ["2025-01-01"]},
        {"handle": "e", "deleted": False, "types": ["info:eu-repo/semantics/doctoralThesis"], "dates": []},
        {
            "handle": "f",
            "deleted": False,
            "types": ["info:eu-repo/semantics/doctoralThesis"],
            "dates": ["2025-05-09", "info:eu-repo/date/embargoEnd/2028-05-08"],
        },
    ]
    selected = select_dei_doctoral_theses(records)
    # b (2023) and e (no date) now survive too — the only exclusions left are
    # wrong type (c) and deleted (d): no publication-year floor any more.
    assert [r["handle"] for r in selected] == ["a", "b", "e", "f"]


def test_find_download_link_prefers_bitstream_over_decoy():
    html = (
        '<a href="/bitstream/10316/119251/1/Thesis.pdf">View</a>'
        '<a href="/bitstream/10316/119251/-1/Thesis.pdf">cite</a>'
    )
    assert find_download_link(html) == "https://estudogeral.uc.pt/bitstream/10316/119251/1/Thesis.pdf"


def test_find_download_link_skips_decoy_falls_back_to_retrieve():
    html = (
        '<a href="/bitstream/10316/119257/-1/PhD.pdf">cite</a>'
        '<a href="/retrieve/280261/PhD.pdf">View/Open</a>'
    )
    assert find_download_link(html) == "https://estudogeral.uc.pt/retrieve/280261/PhD.pdf"


def test_find_download_link_none_when_no_link_present():
    assert find_download_link("<html><body>no links here</body></html>") is None


REST_ITEM_JSON = {
    "metadata": [
        {"key": "dc.title", "value": "Collaborative RUL prediction", "language": "eng"},
        {"key": "dc.title.alternative", "value": "Estimacao da vida util", "language": "por"},
        {"key": "dc.contributor.author", "value": "Rosero, Raul", "language": None},
        {"key": "dc.contributor.advisor", "value": "Ribeiro, Bernardete", "language": None},
        {"key": "dc.date.issued", "value": "2025-04-24", "language": None},
        {"key": "dc.subject", "value": "Federated Learning", "language": "eng"},
        {"key": "dc.subject", "value": "Aprendizagem federada", "language": "por"},
        {"key": "dc.description.abstract", "value": "English abstract.", "language": "eng"},
        {"key": "dc.description.abstract", "value": "Resumo em portugues.", "language": "por"},
        {"key": "dc.rights", "value": "openAccess", "language": None},
    ],
    "bitstreams": [
        {"id": 280261, "name": "PhD.pdf", "mimeType": "application/pdf", "sizeBytes": 49200765},
        {"id": 280262, "name": "license.txt", "mimeType": "text/plain", "sizeBytes": 100},
    ],
}


def test_parse_item_metadata_prefers_english_title_and_splits_by_language():
    fields = parse_item_metadata(REST_ITEM_JSON, "10316/119257")
    assert fields["title"] == "Collaborative RUL prediction"
    assert fields["authors"] == ["Rosero, Raul"]
    assert fields["supervisors"] == ["Ribeiro, Bernardete"]
    assert fields["date"] == "2025-04-24"
    assert fields["keywords"] == ["Federated Learning", "Aprendizagem federada"]
    assert fields["abstract_en"] == "English abstract."
    assert fields["abstract_pt"] == "Resumo em portugues."
    assert fields["rights"] == "openAccess"
    assert fields["pdf_bitstreams"] == [{"id": 280261, "name": "PhD.pdf", "size_bytes": 49200765}]


def test_parse_item_metadata_falls_back_when_no_english_title():
    raw = {
        "metadata": [{"key": "dc.title", "value": "Titulo em portugues", "language": "por"}],
        "bitstreams": [],
    }
    fields = parse_item_metadata(raw, "10316/x")
    assert fields["title"] == "Titulo em portugues"


def test_handle_to_slug():
    assert handle_to_slug("10316/119257") == "10316-119257"


def test_build_front_matter_and_render_markdown_roundtrip():
    fields = parse_item_metadata(REST_ITEM_JSON, "10316/119257")
    fields["full_text"] = True
    fm = build_front_matter(
        fields, "https://estudogeral.uc.pt/handle/10316/119257", ["com_10316_255"]
    )
    assert fm["handle"] == "10316/119257"
    assert fm["source_url"] == "https://estudogeral.uc.pt/handle/10316/119257"
    assert fm["full_text"] is True
    assert fm["oai_sets"] == ["com_10316_255"]

    md = render_markdown(fm, "Full extracted body text.")
    assert md.startswith("---\n")
    assert "handle: 10316/119257" in md
    assert "oai_sets:\n- com_10316_255\n" in md
    assert "# Collaborative RUL prediction" in md
    assert "Full extracted body text." in md


def test_render_markdown_placeholder_when_no_body():
    fields = parse_item_metadata(REST_ITEM_JSON, "10316/119257")
    fields["full_text"] = False
    fm = build_front_matter(fields, "https://estudogeral.uc.pt/handle/10316/119257", [])
    md = render_markdown(fm, "")
    assert "full text not available" in md


EXISTING_MD = """---
handle: 10316/119257
title: Collaborative RUL prediction
authors:
- Rosero, Raul
supervisors:
- Ribeiro, Bernardete
date: '2025-04-24'
keywords:
- Federated Learning
abstract_pt: 'Resumo em portugues.

  Com uma segunda linha --- e um tracinho.'
abstract_en: An abstract in English.
source_url: https://estudogeral.uc.pt/handle/10316/119257
rights: openAccess
full_text: true
---

# Collaborative RUL prediction

Body line one.

---

Body line two, after a horizontal rule.
"""


def test_rewrite_front_matter_adds_oai_sets_and_touches_nothing_else():
    """The backfill of the existing corpus is this function, so its whole job
    is that each of ~181 file diffs is the added `oai_sets` lines alone."""
    out = rewrite_front_matter(EXISTING_MD, ["com_10316_255", "com_10316_47572"])

    assert out == EXISTING_MD.replace(
        "full_text: true\n---",
        "full_text: true\noai_sets:\n- com_10316_255\n- com_10316_47572\n---",
    )


def test_rewrite_front_matter_preserves_a_body_containing_the_delimiter():
    """A thesis body full of extracted PDF text really does contain `---`
    lines; re-rendering from a heading plus a stripped body would eat them."""
    out = rewrite_front_matter(EXISTING_MD, ["com_10316_255"])
    assert out.endswith("Body line two, after a horizontal rule.\n")
    assert "\n---\n\nBody line two" in out


def test_rewrite_front_matter_refuses_a_file_without_front_matter():
    with pytest.raises(ValueError, match="front matter"):
        rewrite_front_matter("# Just a heading\n\nand a body.\n", ["com_10316_255"])


def test_the_rewrite_round_trip_keeps_bare_CRs_in_the_body(tmp_path):
    """24 of the committed theses carry bare CRs in their extracted PDF text.
    Reading them with universal newlines and writing LF back changes
    thousands of body lines in a diff that is supposed to be four added
    lines — so the backfill's file IO must not translate newlines."""
    path = tmp_path / "10316-24429.md"
    original = EXISTING_MD.replace("Body line one.", "Agradecimentos\t \r Body line one.")
    path.write_bytes(original.encode("utf-8"))

    write_md_verbatim(path, rewrite_front_matter(read_md_verbatim(path), ["com_10316_255"]))

    assert path.read_bytes() == original.replace(
        "full_text: true\n---", "full_text: true\noai_sets:\n- com_10316_255\n---"
    ).encode("utf-8")


def _record(handle, set_specs):
    return {"handle": handle, "deleted": False, "types": [], "dates": [], "set_specs": set_specs}


def test_merge_by_handle_processes_a_cross_listed_thesis_once():
    """Frederico's dedup requirement: INESCC/ISR/IT overlap heavily with DEI,
    and a handle in three sets must not be downloaded three times."""
    merged = merge_by_handle(
        {
            "com_10316_255": [_record("10316/a", ["com_10316_255"]),
                              _record("10316/b", ["com_10316_255", "com_10316_27713"])],
            "com_10316_27713": [_record("10316/b", ["com_10316_255", "com_10316_27713"]),
                                _record("10316/c", ["com_10316_27713"])],
            "com_10316_47572": [_record("10316/a", ["com_10316_255"])],
        }
    )
    assert [r["handle"] for r in merged] == ["10316/a", "10316/b", "10316/c"]


def test_merge_by_handle_keeps_the_first_sets_record():
    """First-seen wins and it is allowed to, because every copy of a record
    carries the same complete header membership."""
    merged = merge_by_handle(
        {
            "com_10316_255": [_record("10316/a", ["com_10316_255", "com_10316_27710"])],
            "com_10316_27710": [_record("10316/a", ["com_10316_255", "com_10316_27710"])],
        }
    )
    assert len(merged) == 1
    assert merged[0]["set_specs"] == ["com_10316_255", "com_10316_27710"]


def test_carried_forward_entry_keeps_the_old_outcome_and_adds_origin():
    """Nothing was re-fetched for a front-matter-only rewrite, so the old
    entry's download verdict is still the true one."""
    entry = carried_forward_entry(
        {"handle": "10316/a", "source_url": "https://e/handle/10316/a",
         "full_text": True, "pdf_bytes": 1234},
        "10316/a",
        ["com_10316_255"],
    )
    assert entry == {
        "handle": "10316/a",
        "source_url": "https://e/handle/10316/a",
        "full_text": True,
        "pdf_bytes": 1234,
        "oai_sets": ["com_10316_255"],
    }


def test_carried_forward_entry_synthesises_one_when_the_manifest_has_no_row():
    entry = carried_forward_entry(None, "10316/a", ["com_10316_255"])
    assert entry == {
        "handle": "10316/a",
        "source_url": "https://estudogeral.uc.pt/handle/10316/a",
        "oai_sets": ["com_10316_255"],
    }


def test_harvest_sets_are_the_five_requested_sets():
    """CISUC's own community (com_10316_27707, measured 0 theses) is
    deliberately NOT in scope. col_10316_15519 (the university-wide
    doctoral-theses collection) was added to catch theses cross-listed
    under none of DEI/INESCC/ISR/IT — see the card."""
    assert HARVEST_SETS == {
        "com_10316_255": "DEI",
        "com_10316_27710": "INESCC",
        "com_10316_27713": "ISR",
        "com_10316_47572": "IT",
        "col_10316_15519": "UC",
    }
