"""OAI-PMH enumeration of estudogeral.uc.pt's doctoral-thesis population.

`HARVEST_SETS` is the scope: DEI plus the three institutes CISUC researchers
also deposit under (INESCC, ISR, IT). `run.py` enumerates each and merges by
handle, because the same thesis is routinely listed in several of them.

No deposit-date floor: `fetch_all_records` harvests a community set's full
history (DEI's `com_10316_255` is ~891 records all-time), and `select_dei_doctoral_theses`
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

#: The communities this corpus harvests, and the short label each stands for.
#:
#: DEI alone was the corpus until CISUC researchers turned out to deposit under
#: the institutes they also belong to, so a thesis cross-listed nowhere near
#: DEI was invisible to the harvest. The map is a constant and not a config
#: file because adding a community is a corpus-scope decision someone has to
#: make on a card, not a knob to turn.
#:
#: `com_10316_27707` (CISUC's own community) is deliberately absent: measured
#: 0 theses. Labels are for the run output and for grouping queries over
#: `thesis_sets`; the seed stores the raw spec, never the label.
HARVEST_SETS = {
    "com_10316_255": "DEI",
    "com_10316_27710": "INESCC",
    "com_10316_27713": "ISR",
    "com_10316_47572": "IT",
}

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

DOCTORAL_TYPE = "info:eu-repo/semantics/doctoralThesis"


def parse_record(record_el):
    """Pure: one <record> element -> {identifier, handle, deleted, types, dates, set_specs}.

    `set_specs` is the header's COMPLETE set membership — communities and
    collections, including ones we never enumerate — and the endpoint sends
    all of it whichever set the record was reached through. That is why
    recording origin costs no extra request: enumerating DEI already reports
    that a thesis is also in ISR.
    """
    header = record_el.find("oai:header", NS)
    identifier = header.findtext("oai:identifier", default="", namespaces=NS)
    handle = identifier.rsplit(":", 1)[-1] if identifier else ""
    deleted = header.get("status") == "deleted"
    set_specs = [s.text for s in header.findall("oai:setSpec", NS) if s.text]
    dc = record_el.find(".//oai_dc:dc", NS)
    types = [t.text for t in dc.findall("dc:type", NS)] if dc is not None else []
    dates = [d.text for d in dc.findall("dc:date", NS)] if dc is not None else []
    return {
        "identifier": identifier,
        "handle": handle,
        "deleted": deleted,
        "types": types,
        "dates": dates,
        "set_specs": set_specs,
    }


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
