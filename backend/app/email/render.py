"""Renders an Edition into the newsletter HTML -- the same markup is reused
for the PDF export (see app/pdf/render.py) so both outputs stay in sync.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.edition import Edition

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

SECTION_LABELS: dict[str, str] = {
    "top_story": "Top Stories",
    "general": "General",
    "safety": "Safety",
    "finance": "Finance",
    "fleet": "Fleet",
    "routes": "Routes",
    "regulatory": "Regulatory",
    "sustainability": "Sustainability",
    "labor": "Labor",
    "airport": "Airports",
}


def render_newsletter_html(edition: Edition) -> str:
    by_section: dict[str, list] = {}
    for edition_article in sorted(edition.articles, key=lambda ea: (ea.section, ea.rank)):
        by_section.setdefault(edition_article.section, []).append(edition_article.article)

    sections = []
    section_order = ["top_story", *[s for s in by_section if s != "top_story"]]
    for section_key in section_order:
        articles = by_section.get(section_key)
        if not articles:
            continue
        sections.append(
            {
                "label": SECTION_LABELS.get(section_key, section_key.title()),
                "articles": [
                    {
                        "headline": (a.enrichment.headline if a.enrichment else a.title) or a.title,
                        "summary": a.enrichment.summary if a.enrichment else "",
                        "source_name": a.source.name,
                        "url": a.url,
                        "confidence_pct": round((a.enrichment.confidence_score if a.enrichment else 0) * 100),
                        "corroborating_count": a.enrichment.corroborating_source_count if a.enrichment else 1,
                    }
                    for a in articles
                ],
            }
        )

    template = _env.get_template("newsletter.html")
    return template.render(
        headline=edition.headline,
        executive_summary=edition.executive_summary,
        edition_date=edition.edition_date.strftime("%A, %B %-d, %Y"),
        sections=sections,
    )
