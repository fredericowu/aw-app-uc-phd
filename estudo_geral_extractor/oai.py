"""OAI-PMH enumeration of estudogeral.uc.pt's DEI doctoral-thesis population.

`from=` filters the harvest by DEPOSIT datestamp, not publication year, so it
over-fetches on purpose: 28 records deposited since 2024-01-01 in the DEI
community (`com_10316_255`), of which only 18 carry a `dc:date` (publication
year) of 2024 or later. `select_dei_doctoral_theses_2024_plus` does the real
filter, on `dc:type` + `dc:date`, and is a pure function so it can be tested
against a fixture without hitting the live site.
"""
from xml.etree import ElementTree as ET

OAI_BASE = "https://estudogeral.uc.pt/oai/request"
SET_SPEC = "com_10316_255"  # DEI community
METADATA_PREFIX = "oai_dc"
FROM_DATE = "2024-01-01"  # deposit-date floor; over-fetches, see module docstring

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

DOCTORAL_TYPE = "info:eu-repo/semantics/doctoralThesis"


def parse_record(record_el):
    """Pure: one <record> element -> {identifier, handle, deleted, types, dates}."""
    header = record_el.find("oai:header", NS)
    identifier = header.findtext("oai:identifier", default="", namespaces=NS)
    handle = identifier.rsplit(":", 1)[-1] if identifier else ""
    deleted = header.get("status") == "deleted"
    dc = record_el.find(".//oai_dc:dc", NS)
    types = [t.text for t in dc.findall("dc:type", NS)] if dc is not None else []
    dates = [d.text for d in dc.findall("dc:date", NS)] if dc is not None else []
    return {"identifier": identifier, "handle": handle, "deleted": deleted, "types": types, "dates": dates}


def _max_year(dates):
    years = []
    for d in dates:
        try:
            years.append(int(d[:4]))
        except (TypeError, ValueError):
            continue
    return max(years) if years else None


def select_dei_doctoral_theses_2024_plus(records):
    """Pure: records -> handles of non-deleted doctoral theses with dc:date year >= 2024."""
    selected = []
    for r in records:
        if r["deleted"]:
            continue
        if not any(t == DOCTORAL_TYPE for t in r["types"]):
            continue
        year = _max_year(r["dates"])
        if year is not None and year >= 2024:
            selected.append(r)
    return selected


def fetch_all_records(session, set_spec=SET_SPEC, from_date=FROM_DATE, metadata_prefix=METADATA_PREFIX, sleep=None):
    """Paginate ListRecords via resumptionToken. Yields parsed record dicts."""
    params = {"verb": "ListRecords", "metadataPrefix": metadata_prefix, "set": set_spec, "from": from_date}
    while True:
        r = session.get(OAI_BASE, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        list_records = root.find("oai:ListRecords", NS)
        if list_records is None:
            return
        for record_el in list_records.findall("oai:record", NS):
            yield parse_record(record_el)
        token_el = list_records.find("oai:resumptionToken", NS)
        token = token_el.text if token_el is not None else None
        if not token:
            return
        if sleep:
            sleep()
        params = {"verb": "ListRecords", "resumptionToken": token}
