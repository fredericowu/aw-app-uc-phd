"""Front-matter + body -> the committed `estudo_geral/<slug>.md` file."""
import yaml

FRONT_MATTER_KEYS = (
    "handle",
    "title",
    "authors",
    "supervisors",
    "date",
    "keywords",
    "abstract_pt",
    "abstract_en",
    "source_url",
    "rights",
    "full_text",
    "oai_sets",
)


def handle_to_slug(handle):
    """'10316/119257' -> '10316-119257', filesystem-safe."""
    return handle.replace("/", "-")


def build_front_matter(fields, source_url, oai_sets):
    """Pure: parsed REST fields + the item-page URL + the OAI header's set
    membership -> the ordered front-matter dict.

    `full_text` and `rights` are provenance beyond the card's required list —
    they are what makes the one embargoed thesis's missing body legible
    without opening the manifest. `oai_sets` is provenance of the same family:
    the REST payload cannot answer "which communities list this thesis", only
    the OAI header can, so it is passed in alongside `source_url` rather than
    read out of `fields`.
    """
    return {
        "handle": fields["handle"],
        "title": fields["title"],
        "authors": fields["authors"],
        "supervisors": fields["supervisors"],
        "date": fields["date"],
        "keywords": fields["keywords"],
        "abstract_pt": fields["abstract_pt"],
        "abstract_en": fields["abstract_en"],
        "source_url": source_url,
        "rights": fields["rights"],
        "full_text": fields.get("full_text", False),
        "oai_sets": list(oai_sets),
    }


def dump_front_matter(front_matter):
    """Pure: the front-matter dict -> its YAML block, in FRONT_MATTER_KEYS order.

    Factored out of `render_markdown` so `rewrite_front_matter` below dumps
    through exactly the same call: two dump sites with drifting arguments
    would make a re-rendered file differ from a freshly harvested one in ways
    that have nothing to do with the content.
    """
    return yaml.safe_dump(
        {k: front_matter[k] for k in FRONT_MATTER_KEYS},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def split_front_matter(text):
    """Pure: an existing .md's text -> (front-matter dict, everything after it).

    The remainder is returned as the raw string it was, not re-parsed — see
    `rewrite_front_matter`.
    """
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("no YAML front matter delimiters found")
    return yaml.safe_load(parts[1]), parts[2]


def rewrite_front_matter(text, oai_sets):
    """Pure: an existing .md -> the same file with `oai_sets` recorded.

    Used to backfill origin onto theses already on disk, with no network at
    all. The body is carried across as the bytes it already was rather than
    re-rendered from a heading plus extracted text: a 300-page thesis body
    survives nothing cleanly, and the point of this path is that every file's
    diff is the added `oai_sets` lines and nothing else.
    """
    front_matter, body = split_front_matter(text)
    front_matter["oai_sets"] = list(oai_sets)
    return f"---\n{dump_front_matter(front_matter)}---\n{body}"


def render_markdown(front_matter, body_text):
    """Pure: front-matter dict + extracted body text -> the full .md content."""
    fm_yaml = dump_front_matter(front_matter)
    heading = front_matter["title"] or front_matter["handle"]
    body = body_text.strip() if body_text else "*(full text not available — see `rights`/`full_text` above.)*"
    return f"---\n{fm_yaml}---\n\n# {heading}\n\n{body}\n"
