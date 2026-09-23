"""OAI-PMH enumeration of estudogeral.uc.pt's DEI doctoral-thesis population.

No deposit-date floor: `fetch_all_records` harvests the full DEI community
set (`com_10316_255`, ~891 records all-time), and `select_dei_doctoral_theses`
does the real filter, on `dc:type` alone (no `dc:date` floor) — the ~181
`doctoralThesis` records deposited at any time. It is a pure function so it
can be tested against a fixture without hitting the live site. A prior
version of this module floored the harvest at `from=2024-01-01` (deposit
date) and additionally required `dc:date` year >= 2024, yielding 18 theses;
that floor is gone per the corpus-widening decision — corpus scope is a row
attribute in the store, not a harvest-time filter.
"""
from xml.etree import ElementTree as ET

OAI_BASE = "https://estudogeral.uc.pt/oai/request"
SET_SPEC = "com_10316_255"  # DEI community
METADATA_PREFIX = "oai_dc"

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


def select_dei_doctoral_theses(records):
    """Pure: records -> non-deleted doctoral theses, no publication-year floor."""
    selected = []
    for r in records:
        if r["deleted"]:
            continue
        if not any(t == DOCTORAL_TYPE for t in r["types"]):
            continue
        selected.append(r)
    return selected


def fetch_all_records(session, set_spec=SET_SPEC, from_date=None, metadata_prefix=METADATA_PREFIX, sleep=None):
    """Paginate ListRecords via resumptionToken. Yields parsed record dicts.

    `from_date` is a deposit-datestamp floor, omitted by default so this
    harvests the set's full history. Only pass it to reproduce the old
    2024-only over-fetch behaviour (e.g. in a test)."""
    params = {"verb": "ListRecords", "metadataPrefix": metadata_prefix, "set": set_spec}
    if from_date:
        params["from"] = from_date
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
