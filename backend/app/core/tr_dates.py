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
    """20-24 Temmuz 2026, or "30 Mayıs - 1 Haziran 2027" across a month boundary."""
    if starts.month == ends.month and starts.year == ends.year:
        return f"{starts.day}-{ends.day} {MONTHS[starts.month - 1]} {starts.year}"
    return (
        f"{starts.day} {MONTHS[starts.month - 1]} - "
        f"{ends.day} {MONTHS[ends.month - 1]} {ends.year}"
    )
