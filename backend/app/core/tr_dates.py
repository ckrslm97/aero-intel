"""Turkish date formatting.

`strftime("%A")`/`%B` emit English month and weekday names regardless of the
process locale unless a Turkish locale is installed and activated globally --
which is not something to rely on inside a serverless function or a CI runner.
The names are a closed set of 19 words, so spelling them out is both simpler
and deterministic across every environment this runs in.
"""
from datetime import date

MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)

# Indexed by date.weekday(): Monday == 0.
WEEKDAYS = (
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
)


def format_long_date(value: date) -> str:
    """16 Temmuz 2026, Perşembe -- the newsletter/PDF masthead date."""
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}, {WEEKDAYS[value.weekday()]}"


def format_date_range(starts: date, ends: date) -> str:
    """20-24 Temmuz 2026, or "30 Mayıs - 1 Haziran 2027" across a month boundary.

    A range that crosses New Year states BOTH years. Curated events never do --
    they are a 12-month horizon of fairs and holidays -- but campaigns
    routinely do: flypgs publishes long-running partnerships as
    "15 Ekim 2024 / 31 Ağustos 2026", and printing only the end year turns a
    two-year window into a nonsensical ten-month one that runs backwards.
    """
    if starts.year != ends.year:
        return (
            f"{starts.day} {MONTHS[starts.month - 1]} {starts.year} - "
            f"{ends.day} {MONTHS[ends.month - 1]} {ends.year}"
        )
    if starts.month == ends.month:
        return f"{starts.day}-{ends.day} {MONTHS[starts.month - 1]} {starts.year}"
    return (
        f"{starts.day} {MONTHS[starts.month - 1]} - "
        f"{ends.day} {MONTHS[ends.month - 1]} {ends.year}"
    )


def format_short_date(value: date) -> str:
    """2 Mayıs 2026 -- one date, no weekday."""
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def format_optional_range(starts: date | None, ends: date | None) -> str:
    """A date range where either end may be missing.

    Promotions have four nullable date columns because press coverage of a
    campaign is routinely vague, so this is the common case rather than the
    edge case. It says which end is unknown instead of quietly formatting a
    half-range as if it were whole.

    The partial forms avoid Turkish case suffixes on purpose. "2026'dan
    itibaren" needs vowel harmony against how the *number* is pronounced
    ("iki bin yirmi altı" -> 'dan, but 2027 -> 'den), and getting that wrong on
    a public page reads worse than the plain dash form does.
    """
    if starts and ends:
        return format_date_range(starts, ends)
    if starts:
        return f"{format_short_date(starts)} — bitiş belirtilmedi"
    if ends:
        return f"başlangıç belirtilmedi — {format_short_date(ends)}"
    return "Belirtilmedi"
