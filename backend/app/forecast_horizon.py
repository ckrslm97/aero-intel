"""When is a curated institution forecast FOR?

WHY A DATE IS DERIVED AT ALL, AND WHAT IT IS ALLOWED TO MEAN
-----------------------------------------------------------
app/ingest/curated_seed.py stores each institution's horizon in that
institution's OWN wording, and leaves `horizon_months` None wherever the
wording is not itself a month count -- because, in its words, "converting those
to a number would be our arithmetic presented as their forecast".

That rule is not repealed here. `horizon_label` remains the only thing the
forecast TABLE prints, verbatim, and it is still never rewritten. What this
adds is a strictly separate, clearly-labelled *plotting coordinate*: a chart
with a time axis needs an x for each marker, and "Q4 2026" has no x.

The mapping is therefore deliberately conservative and self-declaring:

  +Nm            -> publication_date + N months.  The institution's own count;
                    no judgement involved.
  end-YYYY       -> 31 December YYYY.  "End of 2026" means end of 2026.
  year-end       -> 31 December of the PUBLICATION year.  A mid-2026 note
                    saying "year-end" means its own year, not a later one.
  QN YYYY        -> the quarter's MIDPOINT (Q1 15 Feb, Q2 15 May, Q3 15 Aug,
                    Q4 15 Nov).  A quarter is a span, and pinning it to either
                    edge would claim a precision the bank did not give; the
                    midpoint at least states that it is a span being reduced,
                    which `target_date_basis_tr` says out loud in every tooltip.
  anything else  -> None.  The row keeps its place in the table and simply gets
                    no marker on the chart.

Every derived date carries its basis into the payload, so no surface can print
one as if the institution had published it.

WHY THIS IS A MODULE OF ITS OWN
-------------------------------
Two callers ask "when is this forecast for", and they used to answer it with
two different pieces of code. The API (app/api/v1/kokpit.py) resolved the label
forms above; the repository (app/repositories/curated_repository.py) could only
date a row carrying `horizon_months`, so `only_upcoming` kept forever exactly
the rows the FX board on the same page was already drawing as "vadesi geçti" --
and the Kur Riski tile quoted one of them as its forward-looking endpoint. One
question, one answer, one implementation: the tile, the table and the chart now
agree by construction rather than by review.
"""
import calendar
import re
from datetime import date

_MONTH_END_DAY_DECEMBER = 31

#: Quarter -> (month, day) midpoint. Stated as data so a test asserts the four
#: values directly rather than re-deriving them.
QUARTER_MIDPOINTS: dict[int, tuple[int, int]] = {
    1: (2, 15),
    2: (5, 15),
    3: (8, 15),
    4: (11, 15),
}

_QUARTER_RE = re.compile(r"^q([1-4])\s*(\d{4})$")
_END_YEAR_RE = re.compile(r"^end[-\s]?(\d{4})$")
_MONTHS_RE = re.compile(r"^\+?(\d{1,3})\s*m$")


def _add_months(start: date, months: int) -> date:
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    # Clamp rather than roll over: 31 Aug + 6m is 28/29 Feb, not 3 March.
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def forecast_target_date(
    *, horizon_months: int | None, horizon_label: str, publication_date: date
) -> tuple[date | None, str | None]:
    """The date a forecast is FOR, plus the Turkish sentence explaining how it
    was arrived at. See the module docstring for the whole mapping and for why
    this never touches `horizon_label` itself."""
    label = horizon_label.strip().lower()

    if horizon_months is not None:
        target = _add_months(publication_date, horizon_months)
        return target, f"Kurumun kendi vadesi ({horizon_label}) yayın tarihine eklendi."

    months_match = _MONTHS_RE.match(label)
    if months_match:
        target = _add_months(publication_date, int(months_match.group(1)))
        return target, f"Kurumun kendi vadesi ({horizon_label}) yayın tarihine eklendi."

    end_year_match = _END_YEAR_RE.match(label)
    if end_year_match:
        year = int(end_year_match.group(1))
        return (
            date(year, 12, _MONTH_END_DAY_DECEMBER),
            f"“{horizon_label}” yıl sonu olarak 31 Aralık {year} kabul edildi.",
        )

    if label in {"year-end", "yıl sonu", "yil sonu"}:
        year = publication_date.year
        return (
            date(year, 12, _MONTH_END_DAY_DECEMBER),
            f"“{horizon_label}” yayın yılının sonu, yani 31 Aralık {year} kabul edildi.",
        )

    quarter_match = _QUARTER_RE.match(label)
    if quarter_match:
        quarter, year = int(quarter_match.group(1)), int(quarter_match.group(2))
        month, day = QUARTER_MIDPOINTS[quarter]
        return (
            date(year, month, day),
            (
                f"“{horizon_label}” bir çeyrek aralığıdır; grafikte çeyreğin "
                f"orta noktası ({day}.{month:02d}.{year}) kullanıldı."
            ),
        )

    return None, None
