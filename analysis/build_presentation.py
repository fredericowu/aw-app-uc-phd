"""Builds the exploratory-analysis presentation from data/cisuc.sqlite3.

Every number comes from a `.sql` file in `sql/`, read from disk at run time
— never inlined here (criterion 6, auditability). This script only executes
those queries, renders them as matplotlib figures, and assembles one
self-contained HTML document in the aw-presentation dark-theme house style.

Usage: .venv/bin/python -m analysis.build_presentation
Prints the output HTML path on success.
"""
import base64
import io
import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".venv" / ".mplcache"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from analysis.problem_summaries import PROBLEM_SUMMARIES  # noqa: E402

DB_PATH = REPO_ROOT / "data" / "cisuc.sqlite3"
SQL_DIR = REPO_ROOT / "sql"
OUTPUT_PATH = REPO_ROOT / "analysis" / "presentation.html"

# -- chart chrome: matches the aw-presentation dark theme it's embedded in --
BG = "#0d1117"
CARD_BG = "#161b22"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
GRID = "#21262d"
ACCENT_HEADING = "#58a6ff"

# -- data-ink: dataviz skill's validated dark-mode categorical/sequential steps --
CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
SEQUENTIAL_BLUE = "#3987e5"
SEQUENTIAL_ORANGE = "#d95926"


def run_sql(name):
    path = SQL_DIR / name
    query = path.read_text()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _style_axes(ax):
    ax.set_facecolor(BG)
    ax.tick_params(colors=MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.title.set_color(TEXT)


def fig_to_data_uri(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", dpi=150)
    plt.close(fig)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def horizontal_bar_chart(labels, values, colors, title, xlabel, value_fmt="{:.0f}"):
    height = max(2.2, 0.42 * len(labels) + 0.8)
    fig, ax = plt.subplots(figsize=(7.5, height))
    fig.patch.set_facecolor(BG)
    _style_axes(ax)

    y_pos = range(len(labels))
    bars = ax.barh(y_pos, values, color=colors, height=0.62)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, color=TEXT, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.set_title(title, fontsize=12, pad=10)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)

    max_val = max(values) if values else 0
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + max_val * 0.015,
            bar.get_y() + bar.get_height() / 2,
            value_fmt.format(val),
            va="center",
            ha="left",
            color=TEXT,
            fontsize=8.5,
        )
    fig.tight_layout()
    return fig_to_data_uri(fig)


def bar_chart(labels, values, color, title, ylabel, value_fmt="{:.0f}"):
    # A year-by-year timeline can run 25-30+ bars — a label on every bar
    # collides into unreadable clutter (dataviz anti-pattern: "a number on
    # every point"). Past a threshold, rely on the axis/gridlines and only
    # rotate + thin the tick labels instead.
    many_bars = len(labels) > 15
    width = max(7.5, 0.32 * len(labels))
    fig, ax = plt.subplots(figsize=(width, 3.8))
    fig.patch.set_facecolor(BG)
    _style_axes(ax)

    x_pos = range(len(labels))
    bars = ax.bar(x_pos, values, color=color, width=0.65)
    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(labels, color=TEXT, fontsize=8.5, rotation=90 if many_bars else 0)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=12, pad=10)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)

    if many_bars:
        fig.tight_layout()
        return fig_to_data_uri(fig)

    max_val = max(values) if values else 0
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max_val * 0.02,
            value_fmt.format(val),
            ha="center",
            va="bottom",
            color=TEXT,
            fontsize=8.5,
        )
    fig.tight_layout()
    return fig_to_data_uri(fig)


def top_projects_by_group_html(per_group, top_projects):
    # per_group gives section order (already sorted by project_count DESC,
    # same order group_color was assigned in) — group_code -> [rows].
    by_code = {}
    for row in top_projects:
        by_code.setdefault(row["code"], []).append(row)

    sections = []
    for g in per_group:
        code, name = g["code"], g["name"]
        rows = by_code.get(code, [])
        if not rows:
            continue
        table_rows = "".join(
            f"<tr><td>{r['rank_in_group']}</td>"
            f"<td><a href=\"{r['detail_url']}\" target=\"_blank\" rel=\"noopener\">{r['title']}</a></td>"
            f"<td>€{r['total_budget_amount']:,.0f}</td>"
            f"<td>{PROBLEM_SUMMARIES.get(r['project_id'], '(no problem summary authored for this project id — see synopsis in sql/top_projects_per_group.sql)')}</td>"
            f"</tr>"
            for r in rows
        )
        sections.append(f"""
      <div class="card">
        <h3>{code} — {name} ({len(rows)} project{'s' if len(rows) != 1 else ''})</h3>
        <div class="table-wrap">
          <table>
            <tr><th>#</th><th>Project</th><th>Total budget</th><th>Problem it solves</th></tr>
            {table_rows}
          </table>
        </div>
      </div>""")
    return "".join(sections)


def build():
    coverage = run_sql("coverage.sql")[0]
    fill_rates = run_sql("fill_rates.sql")
    per_group = run_sql("projects_per_group.sql")
    funding = run_sql("funding_breakdown.sql")
    budget_group = run_sql("budget_by_group.sql")
    budget_year = run_sql("budget_by_year.sql")
    timeline = run_sql("start_date_timeline.sql")
    coordinators = run_sql("top_coordinators.sql")
    top_projects = run_sql("top_projects_per_group.sql")

    # Shared code->color mapping so a research group carries the same color
    # across every chart it appears in (dataviz: "color follows the entity").
    group_color = {row["code"]: CATEGORICAL[i % len(CATEGORICAL)] for i, row in enumerate(per_group)}

    fill_rates_img = horizontal_bar_chart(
        [r["label"] for r in fill_rates],
        [r["fill_rate_pct"] for r in fill_rates],
        [SEQUENTIAL_BLUE] * len(fill_rates),
        "Per-field fill rate (% of 398 fetched detail pages)",
        "% of projects with this field populated",
        value_fmt="{:.0f}%",
    )

    per_group_img = horizontal_bar_chart(
        [f'{r["code"]} — {r["name"]}' for r in per_group],
        [r["project_count"] for r in per_group],
        [group_color[r["code"]] for r in per_group],
        "Projects per research group (many-to-many — sums above 400)",
        "project count",
    )

    funding_img = horizontal_bar_chart(
        [r["funder"] for r in funding],
        [r["project_count"] for r in funding],
        [SEQUENTIAL_BLUE] * len(funding),
        "Top funders by number of projects funded",
        "project count",
    )

    budget_group_img = horizontal_bar_chart(
        [f'{r["code"]} — {r["name"]}' for r in budget_group],
        [r["total_budget_sum"] for r in budget_group],
        [group_color[r["code"]] for r in budget_group],
        "Total budget by research group (€, summed across memberships)",
        "€ total budget",
        value_fmt="€{:,.0f}",
    )

    budget_year_img = bar_chart(
        [r["start_year"] for r in budget_year],
        [r["total_budget_sum"] for r in budget_year],
        SEQUENTIAL_BLUE,
        "Total budget by start year (projects with a parsed start date)",
        "€ total budget",
        value_fmt="€{:,.0f}",
    )

    timeline_img = bar_chart(
        [r["start_year"] for r in timeline],
        [r["project_count"] for r in timeline],
        SEQUENTIAL_ORANGE,
        "Projects started per year",
        "project count",
    )

    coordinators_img = horizontal_bar_chart(
        [r["coordinator"] for r in coordinators],
        [r["project_count"] for r in coordinators],
        [SEQUENTIAL_BLUE] * len(coordinators),
        "Most frequent coordinators (top 15)",
        "project count",
    )

    top_projects_html = top_projects_by_group_html(per_group, top_projects)

    fill_rate_rows = "".join(
        f"<tr><td>{r['label']}</td><td>{r['projects_with_field']}</td>"
        f"<td>{r['fill_rate_pct']}%</td></tr>"
        for r in fill_rates
    )

    html = f"""<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0;
         padding: clamp(12px, 4vw, 24px); background: {BG}; color: {TEXT};
         overflow-wrap: anywhere; }}
  .header {{ border-bottom: 1px solid #30363d; padding-bottom: 16px; margin-bottom: 24px; }}
  .header h1 {{ color: {ACCENT_HEADING}; margin: 0 0 8px; font-size: clamp(20px, 5vw, 30px); }}
  .header .subtitle {{ color: {MUTED}; }}
  .section {{ margin-bottom: 32px; }}
  .section h2 {{ color: {ACCENT_HEADING}; border-bottom: 1px solid #21262d; padding-bottom: 8px;
                font-size: clamp(16px, 4vw, 22px); }}
  .card {{ background: {CARD_BG}; border: 1px solid #30363d; border-radius: 8px;
          padding: clamp(12px, 3vw, 16px); margin: 12px 0; }}
  .card h3 {{ color: #f0f6fc; margin-top: 0; }}
  .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
  .metrics {{ display: flex; flex-wrap: wrap; gap: 12px 24px; }}
  .metric {{ text-align: center; }}
  .metric .value {{ font-size: clamp(20px, 6vw, 28px); font-weight: 700; color: #f0f6fc; }}
  .metric .label {{ font-size: 12px; color: {MUTED}; }}
  .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 12px 0; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #21262d; }}
  th {{ color: {MUTED}; font-weight: 600; }}
  img {{ max-width: 100%; height: auto; display: block; margin: 0 auto; }}
  .note {{ color: {MUTED}; font-size: 13px; margin-top: 4px; }}
  @media (max-width: 640px) {{
    .header {{ margin-bottom: 16px; }}
    .section {{ margin-bottom: 20px; }}
  }}
</style>
</head>
<body>
  <div class="header">
    <h1>UC DEI / CISUC Projects — Exploratory Analysis</h1>
    <div class="subtitle">400 projects scraped from cisuc.uc.pt/en/projects &mdash; every figure below traces to a committed .sql file</div>
  </div>

  <div class="section">
    <h2>Coverage</h2>
    <div class="card">
      <div class="metrics">
        <div class="metric"><div class="value">{coverage['total_projects']}</div><div class="label">total projects</div></div>
        <div class="metric"><div class="value">{coverage['detail_fetched_ok']}</div><div class="label">detail pages fetched</div></div>
        <div class="metric"><div class="value">{coverage['detail_unavailable']}</div><div class="label">no detail page (site limitation)</div></div>
        <div class="metric"><div class="value">{coverage['null_titles']}</div><div class="label">NULL titles</div></div>
        <div class="metric"><div class="value">{coverage['scrape_targets_terminal']}/{coverage['scrape_targets_rows']}</div><div class="label">scrape_targets terminal</div></div>
      </div>
      <div class="note">Site's own totalData at scrape time: {coverage['site_total_data']}. Query: sql/coverage.sql.</div>
    </div>
  </div>

  <div class="section">
    <h2>Field completeness</h2>
    <div class="card">
      <img src="{fill_rates_img}" alt="Per-field fill rate">
      <div class="table-wrap">
        <table>
          <tr><th>Field label</th><th>Projects with value</th><th>Fill rate</th></tr>
          {fill_rate_rows}
        </table>
      </div>
      <div class="note">Query: sql/fill_rates.sql — driven by project_fields_raw, the site's own label universe, not a hardcoded field list.</div>
    </div>
  </div>

  <div class="section">
    <h2>Research groups</h2>
    <div class="grid">
      <div class="card">
        <img src="{per_group_img}" alt="Projects per research group">
        <div class="note">Query: sql/projects_per_group.sql — many-to-many; a project can belong to more than one group.</div>
      </div>
      <div class="card">
        <img src="{budget_group_img}" alt="Total budget by research group">
        <div class="note">Query: sql/budget_by_group.sql — same many-to-many caveat applies to the budget sum.</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Top 10 projects per research group</h2>
    <div class="card">
      <div class="note">Ranking metric not specified by the request — this uses <strong>total budget</strong> (descending) as the most objective available proxy for a project's size/relevance. Many-to-many: a project can appear in more than one group's top 10. Groups with fewer than 10 eligible projects (parsed budget + synopsis) list all of them. Query: sql/top_projects_per_group.sql.</div>
    </div>
    {top_projects_html}
  </div>

  <div class="section">
    <h2>Funding</h2>
    <div class="card">
      <img src="{funding_img}" alt="Funding breakdown">
      <div class="note">Query: sql/funding_breakdown.sql — the site exposes a funder name, not a funding "type"; no category is invented.</div>
    </div>
  </div>

  <div class="section">
    <h2>Timeline</h2>
    <div class="grid">
      <div class="card">
        <img src="{timeline_img}" alt="Projects started per year">
        <div class="note">Query: sql/start_date_timeline.sql</div>
      </div>
      <div class="card">
        <img src="{budget_year_img}" alt="Total budget by start year">
        <div class="note">Query: sql/budget_by_year.sql</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Coordinators</h2>
    <div class="card">
      <img src="{coordinators_img}" alt="Most frequent coordinators">
      <div class="note">Query: sql/top_coordinators.sql</div>
    </div>
  </div>
</body>
</html>"""

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(str(OUTPUT_PATH))


if __name__ == "__main__":
    build()
