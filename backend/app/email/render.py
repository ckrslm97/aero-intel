"""Renders an Edition into the newsletter HTML -- the same markup is reused
for the PDF export (see app/pdf/render.py) so both outputs stay in sync.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings
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


LEAD_SUMMARY_CHARS = 260
# The newsletter is a doorway, not an archive: a lead with a short summary,
# then headline links. Everything else lives one click away on the site.
HEADLINE_LINK_COUNT = 7
PER_SECTION_LINKS = 3
MAX_SECTIONS = 5


def _site_url() -> str:
    settings = get_settings()
    if settings.public_site_url:
        return settings.public_site_url.rstrip("/")
    for origin in settings.cors_origins:
        if origin.startswith("https://"):
            return origin.rstrip("/")
    return "http://localhost:3000"


def _sections_with_all_articles(edition: Edition) -> list[dict]:
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
    return sections


def render_edition_full_html(edition: Edition) -> str:
    """The complete edition -- every article with its summary. This is what the
    PDF is rendered from; the emailed newsletter is deliberately a short
    headline digest instead (see render_newsletter_html)."""
    template = _env.get_template("edition_full.html")
    return template.render(
        headline=edition.headline,
        executive_summary=edition.executive_summary,
        edition_date=format_long_date(edition.edition_date),
        sections=_sections_with_all_articles(edition),
    )


def render_newsletter_html(edition: Edition, digest: str | None = None) -> str:
    """`digest` is the İçgörüler page's "pattern of the day" paragraph. Optional
    so the PDF path (which has no DB session at render time) can omit it."""
    by_section: dict[str, list] = {}
    for edition_article in sorted(edition.articles, key=lambda ea: (ea.section, ea.rank)):
        by_section.setdefault(edition_article.section, []).append(edition_article.article)

    top_articles = [_article_context(a) for a in by_section.get("top_story", [])]
    lead = top_articles[0] if top_articles else None
    if lead and len(lead["summary"]) > LEAD_SUMMARY_CHARS:
        lead = {**lead, "summary": lead["summary"][:LEAD_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"}

    sections = []
    for section_key, articles in by_section.items():
        if section_key == "top_story":
            continue
        sections.append(
            {
                "label": SECTION_LABELS.get(section_key, section_key.title()),
                "articles": [_article_context(a) for a in articles[:PER_SECTION_LINKS]],
                "total": len(articles),
            }
        )
    sections.sort(key=lambda s: -s["total"])

    site_url = _site_url()
    template = _env.get_template("newsletter.html")
    return template.render(
        headline=edition.headline,
        executive_summary=edition.executive_summary,
        edition_date=format_long_date(edition.edition_date),
        lead=lead,
        headlines=top_articles[1 : HEADLINE_LINK_COUNT + 1],
        sections=sections[:MAX_SECTIONS],
        digest=digest,
        site_url=site_url,
        newspaper_url=f"{site_url}/newspaper/{edition.edition_date.isoformat()}",
        insights_url=f"{site_url}/insights",
        biz_url=f"{site_url}/biz",
        archive_url=f"{site_url}/archive",
    )
