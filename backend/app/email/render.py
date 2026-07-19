"""Renders an Edition into the newsletter HTML -- the same markup is reused
for the PDF export (see app/pdf/render.py) so both outputs stay in sync.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.tr_dates import format_long_date
from app.models.article import Article
from app.models.edition import Edition

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

# Kept identical to the web section labels in
# frontend/src/app/newspaper/[date]/page.tsx -- a reader who follows the PDF
# link from the newsletter should land on sections with the same names.
SECTION_LABELS: dict[str, str] = {
    "top_story": "Öne Çıkanlar",
    "general": "Genel",
    "revenue_management": "Gelir Yönetimi",
    "safety": "Emniyet",
    "finance": "Finans",
    "fleet": "Filo",
    "network": "Ağ & Rota",
    "regulatory": "Regülasyon",
    "sustainability": "Sürdürülebilirlik",
    "labor": "İşgücü",
    "airport": "Havalimanı",
    "events": "Etkinlik",
}


def _article_context(article: Article) -> dict:
    enrichment = article.enrichment
    # Same rule as the web card (frontend/src/components/article-card.tsx):
    # show Turkish only when a translation-capable LLM actually produced it,
    # otherwise show the original and label it -- never pass English off as
    # Turkish by silently falling back.
    is_translated = enrichment is not None and enrichment.translated_at is not None
    headline = (is_translated and enrichment.headline_tr) or (
        enrichment.headline if enrichment else None
    ) or article.title
    summary = (is_translated and enrichment.summary_tr) or (
        enrichment.summary if enrichment else ""
    )
    return {
        "headline": headline,
        "summary": summary,
        "is_translated": is_translated,
        "source_name": article.source.name,
        "url": article.url,
        "confidence_pct": round((enrichment.confidence_score if enrichment else 0) * 100),
        "corroborating_count": enrichment.corroborating_source_count if enrichment else 1,
    }


def render_newsletter_html(edition: Edition, digest: str | None = None) -> str:
    """`digest` is the İçgörüler page's "pattern of the day" paragraph. Optional
    so the PDF path (which has no DB session at render time) can omit it."""
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
                "articles": [_article_context(a) for a in articles],
            }
        )

    template = _env.get_template("newsletter.html")
    return template.render(
        headline=edition.headline,
        executive_summary=edition.executive_summary,
        edition_date=format_long_date(edition.edition_date),
        sections=sections,
        digest=digest,
    )
