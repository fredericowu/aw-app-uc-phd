"""Fixture-based tests for estudo_geral_extractor's pure functions.

Same convention as tests/test_parse.py and tests/test_detail_parser.py:
only parsing/selection logic is tested here, never the live HTTP paths
(oai.fetch_all_records, restapi.fetch_item, download.fetch_item_page/
download_pdf) — see pyproject.toml's coverage-gate comment for why.
"""
from xml.etree import ElementTree as ET

from estudo_geral_extractor.download import find_download_link
from estudo_geral_extractor.markdown import build_front_matter, handle_to_slug, render_markdown
from estudo_geral_extractor.oai import parse_record, select_dei_doctoral_theses_2024_plus
from estudo_geral_extractor.restapi import parse_item_metadata

OAI_RECORD_XML = """
<record xmlns="http://www.openarchives.org/OAI/2.0/">
  <header>
    <identifier>oai:estudogeral.uc.pt:10316/119257</identifier>
    <datestamp>2025-06-03T22:07:48Z</datestamp>
    <setSpec>com_10316_255</setSpec>
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


def test_parse_record_deleted_has_no_metadata():
    el = ET.fromstring(OAI_DELETED_RECORD_XML)
    r = parse_record(el)
    assert r["deleted"] is True
    assert r["types"] == []
    assert r["dates"] == []


def test_select_filters_type_year_and_deleted():
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
    selected = select_dei_doctoral_theses_2024_plus(records)
    assert [r["handle"] for r in selected] == ["a", "f"]


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
    fm = build_front_matter(fields, "https://estudogeral.uc.pt/handle/10316/119257")
    assert fm["handle"] == "10316/119257"
    assert fm["source_url"] == "https://estudogeral.uc.pt/handle/10316/119257"
    assert fm["full_text"] is True

    md = render_markdown(fm, "Full extracted body text.")
    assert md.startswith("---\n")
    assert "handle: 10316/119257" in md
    assert "# Collaborative RUL prediction" in md
    assert "Full extracted body text." in md


def test_render_markdown_placeholder_when_no_body():
    fields = parse_item_metadata(REST_ITEM_JSON, "10316/119257")
    fields["full_text"] = False
    fm = build_front_matter(fields, "https://estudogeral.uc.pt/handle/10316/119257")
    md = render_markdown(fm, "")
    assert "full text not available" in md
