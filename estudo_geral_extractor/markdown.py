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
)


def handle_to_slug(handle):
    """'10316/119257' -> '10316-119257', filesystem-safe."""
    return handle.replace("/", "-")


def build_front_matter(fields, source_url):
    """Pure: parsed REST fields + the item-page URL -> the ordered front-matter dict.

    `full_text` and `rights` are provenance beyond the card's required list —
    they are what makes the one embargoed thesis's missing body legible
    without opening the manifest.
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
    }


def render_markdown(front_matter, body_text):
    """Pure: front-matter dict + extracted body text -> the full .md content."""
    fm_yaml = yaml.safe_dump(
        {k: front_matter[k] for k in FRONT_MATTER_KEYS},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    heading = front_matter["title"] or front_matter["handle"]
    body = body_text.strip() if body_text else "*(full text not available — see `rights`/`full_text` above.)*"
    return f"---\n{fm_yaml}---\n\n# {heading}\n\n{body}\n"
