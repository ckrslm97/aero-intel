"""Veri çekim frekansı planlayıcısı.

OND tipine göre çekim sıklığını TAM OTOMATİK belirler:

- **Local**  (TR çıkışlı veya TR varışlı)  -> haftalık  (7 gün)
- **Beyond** (TR içermeyen transit rotalar) -> aylık    (30 gün)

`due_onds()` fonksiyonu, arşiv indeksine bakarak hangi OND'lerin çekim
zamanının geldiğini hesaplar. GUI'deki "Sadece zamanı gelenler" seçeneği
ve `--cli --due` modu bu fonksiyonu kullanır. Hiç çekilmemiş OND her
zaman "due" kabul edilir.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from core.enrich import ond_type_of
from core.logging_config import get_logger
from core.ond import OND

log = get_logger("scheduler")

#: OND tipi -> çekim aralığı (gün). Tek noktadan değiştirilebilir.
FREQUENCY_DAYS: dict[str, int] = {
    "Local": 7,     # haftalık
    "Beyond": 30,   # aylık
}


def interval_for(ond: OND) -> int:
    """Bir OND için çekim aralığını (gün) döndürür."""
    return FREQUENCY_DAYS[ond_type_of(ond.origin, ond.destination)]


def last_collection_dates(archive_index: list[dict]) -> dict[tuple[str, str, str], date]:
    """Arşivden her (havayolu, origin, dest) için son CollDate'i çıkarır."""
    last: dict[tuple[str, str, str], date] = {}
    for run in archive_index:
        try:
            cd = datetime.fromisoformat(str(run.get("coll_date", ""))[:10]).date()
        except ValueError:
            continue
        for airline in run.get("airlines", []):
            for route in run.get("onds", []):
                if "-" not in route:
                    continue
                o, d = route.split("-", 1)
                key = (airline, o, d)
                if key not in last or cd > last[key]:
                    last[key] = cd
    return last


def due_onds(onds: list[OND], archive_index: list[dict],
             today: date | None = None) -> list[OND]:
    """Çekim zamanı gelmiş OND'leri döndürür.

    Kural: son çekimin üzerinden Local için 7, Beyond için 30 gün
    geçtiyse (veya hiç çekilmemişse) OND listeye girer.
    """
    today = today or date.today()
    last = last_collection_dates(archive_index)
    due: list[OND] = []
    for ond in onds:
        key = (ond.airline, ond.origin, ond.destination)
        prev = last.get(key)
        interval = interval_for(ond)
        if prev is None or (today - prev) >= timedelta(days=interval):
            due.append(ond)
        else:
            log.debug("Atlandı (frekans): %s (%d gün dolmadı)", ond, interval)
    log.info("Frekans planı: %d/%d OND çekilecek.", len(due), len(onds))
    return due
