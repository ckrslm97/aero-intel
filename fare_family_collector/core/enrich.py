"""Veri zenginleştirme ve kalite katmanı.

Her fare kaydına platform seviyesinde analiz alanları ekler:

- ``coll_date``      : Collection Date (YYYY-MM-DD)
- ``season``         : Summer (Nisan-Eylül) / Winter (Ekim-Mart)
- ``ond_type``       : Local (TR çıkışlı/varışlı) / Beyond (TR içermeyen)
- ``region``         : Rotanın bölgesi (TR olmayan uç noktaya göre)
- ``carrier_type``   : Legacy / Low Cost
- ``price_usd``      : Güvenilir kur tablosuyla USD'ye çevrilmiş fiyat
                       (orijinal ``price`` + ``currency`` korunur)

Ayrıca temel veri kalite kontrollerini (eksik, tutarsız, duplicate,
para birimi hatası) içerir.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Iterable

from core.logging_config import get_logger
from core.models import FareBrand

log = get_logger("enrich")

# ---------------------------------------------------------------------------
# Sezon / OND tipi
# ---------------------------------------------------------------------------

#: Türkiye havalimanları — Local/Beyond ayrımının temeli.
TR_AIRPORTS: frozenset[str] = frozenset({
    "IST", "SAW", "ESB", "ADB", "AYT", "DLM", "BJV", "TZX", "GZT",
    "ADA", "ASR", "KYA", "VAN", "DIY", "SZF", "HTY", "MLX", "EZS",
})

#: Yaz sezonu ayları (Nisan-Eylül). Diğer aylar Winter.
SUMMER_MONTHS: frozenset[int] = frozenset({4, 5, 6, 7, 8, 9})


def season_of(d: date | str) -> str:
    """Sezonu otomatik hesaplar: Nisan-Eylül = Summer, Ekim-Mart = Winter."""
    if isinstance(d, str):
        d = datetime.fromisoformat(d[:10]).date()
    return "Summer" if d.month in SUMMER_MONTHS else "Winter"


def ond_type_of(origin: str, destination: str) -> str:
    """OND tipini hesaplar: TR çıkışlı/varışlı = Local, aksi = Beyond."""
    o, d = origin.upper().strip(), destination.upper().strip()
    return "Local" if (o in TR_AIRPORTS or d in TR_AIRPORTS) else "Beyond"


# ---------------------------------------------------------------------------
# Region eşlemesi
# ---------------------------------------------------------------------------

#: Havalimanı -> bölge. Eksik kodlar "Other" olarak işaretlenir; yeni
#: havalimanı eklemek için yalnızca bu tabloyu genişletmek yeterlidir.
AIRPORT_REGION: dict[str, str] = {
    # Türkiye
    **{a: "Turkey" for a in TR_AIRPORTS},
    # Avrupa
    "FRA": "Europe", "MUC": "Europe", "CDG": "Europe", "ORY": "Europe",
    "LHR": "Europe", "LGW": "Europe", "AMS": "Europe", "MAD": "Europe",
    "BCN": "Europe", "FCO": "Europe", "MXP": "Europe", "ZRH": "Europe",
    "GVA": "Europe", "VIE": "Europe", "BRU": "Europe", "CPH": "Europe",
    "ARN": "Europe", "OSL": "Europe", "HEL": "Europe", "ATH": "Europe",
    "LIS": "Europe", "DUB": "Europe", "WAW": "Europe", "PRG": "Europe",
    "BUD": "Europe", "OTP": "Europe", "SOF": "Europe", "BEG": "Europe",
    # Kuzey Amerika
    "JFK": "N. America", "EWR": "N. America", "IAD": "N. America",
    "ORD": "N. America", "LAX": "N. America", "SFO": "N. America",
    "MIA": "N. America", "BOS": "N. America", "YYZ": "N. America",
    "YUL": "N. America", "ATL": "N. America", "DFW": "N. America",
    # Orta Doğu
    "DXB": "M. East", "AUH": "M. East", "DOH": "M. East",
    "JED": "M. East", "RUH": "M. East", "KWI": "M. East",
    "BAH": "M. East", "AMM": "M. East", "BEY": "M. East", "TLV": "M. East",
    # Asya / Uzak Doğu
    "SIN": "Asia", "HKG": "Asia", "NRT": "Asia", "HND": "Asia",
    "ICN": "Asia", "PVG": "Asia", "PEK": "Asia", "BKK": "Asia",
    "KUL": "Asia", "DEL": "Asia", "BOM": "Asia", "CGK": "Asia",
    "MNL": "Asia", "TPE": "Asia", "HAN": "Asia", "SGN": "Asia",
    # Afrika
    "CAI": "Africa", "JNB": "Africa", "NBO": "Africa", "ADD": "Africa",
    "CMN": "Africa", "ALG": "Africa", "TUN": "Africa", "LOS": "Africa",
    # Okyanusya / Güney Amerika
    "SYD": "Oceania", "MEL": "Oceania", "AKL": "Oceania",
    "GRU": "S. America", "EZE": "S. America", "BOG": "S. America",
}


def region_of(origin: str, destination: str) -> str:
    """Rotanın bölgesini döndürür.

    Kural: Local rotalarda TR olmayan uç noktanın bölgesi; Beyond
    rotalarda varış noktasının bölgesi kullanılır.
    """
    o, d = origin.upper().strip(), destination.upper().strip()
    if o in TR_AIRPORTS and d in TR_AIRPORTS:
        return "Turkey"
    if o in TR_AIRPORTS:
        return AIRPORT_REGION.get(d, "Other")
    if d in TR_AIRPORTS:
        return AIRPORT_REGION.get(o, "Other")
    return AIRPORT_REGION.get(d, "Other")


# ---------------------------------------------------------------------------
# Taşıyıcı tipi
# ---------------------------------------------------------------------------

#: Düşük maliyetli taşıyıcılar. Listede olmayan her kod Legacy kabul edilir.
LOW_COST_CARRIERS: frozenset[str] = frozenset({
    "PC", "XQ", "FR", "W6", "U2", "VY", "6E", "AK", "FZ", "G9",
    "TO", "HV", "DY", "D8", "SG", "NK", "F9", "WN", "JQ", "TR",
})


def carrier_type_of(airline: str) -> str:
    """Taşıyıcı tipini döndürür: 'Low Cost' veya 'Legacy'."""
    return "Low Cost" if airline.upper().strip() in LOW_COST_CARRIERS else "Legacy"


# ---------------------------------------------------------------------------
# Para birimi -> USD
# ---------------------------------------------------------------------------

#: USD dönüşüm kurları (1 birim = X USD). Üretimde .env üzerinden veya bir
#: kur API'siyle güncellenebilir; FX_<KOD>=oran ortam değişkeni tabloyu ezer.
FX_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.09,
    "GBP": 1.28,
    "TRY": 0.024,
    "CHF": 1.13,
    "AED": 0.2723,
    "QAR": 0.2747,
    "SAR": 0.2666,
    "JPY": 0.0064,
    "CNY": 0.138,
    "SGD": 0.75,
    "HKD": 0.128,
    "KRW": 0.00073,
    "INR": 0.0117,
    "AUD": 0.66,
    "CAD": 0.73,
    "SEK": 0.096,
    "NOK": 0.094,
    "DKK": 0.146,
    "THB": 0.031,
    "TND": 0.34,
    "PLN": 0.256,
}


def _fx_rate(currency: str) -> float | None:
    """Kur oranını döndürür; .env (FX_EUR=1.10 gibi) tabloyu ezebilir."""
    code = currency.upper().strip()
    env_val = os.getenv(f"FX_{code}")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            log.warning("Geçersiz FX_%s değeri: %s", code, env_val)
    return FX_TO_USD.get(code)


def to_usd(price: float | None, currency: str) -> float | None:
    """Fiyatı USD'ye çevirir; kur bilinmiyorsa None döner (kalite uyarısı)."""
    if price is None:
        return None
    rate = _fx_rate(currency or "USD")
    if rate is None:
        return None
    return round(price * rate, 2)


# ---------------------------------------------------------------------------
# Zenginleştirme
# ---------------------------------------------------------------------------

def enrich_fare(fare: FareBrand, coll_date: str | None = None) -> FareBrand:
    """Tek bir fare kaydına tüm platform alanlarını ekler (yerinde)."""
    fare.coll_date = coll_date or date.today().isoformat()
    fare.season = season_of(fare.coll_date)
    fare.ond_type = ond_type_of(fare.origin, fare.destination)
    fare.region = region_of(fare.origin, fare.destination)
    fare.carrier_type = carrier_type_of(fare.airline)
    fare.price_usd = to_usd(fare.price, fare.currency)
    return fare


def enrich_all(fares: Iterable[FareBrand], coll_date: str | None = None) -> list[FareBrand]:
    """Bir kayıt listesini topluca zenginleştirir."""
    cd = coll_date or date.today().isoformat()
    return [enrich_fare(f, cd) for f in fares]


# ---------------------------------------------------------------------------
# Veri kalitesi
# ---------------------------------------------------------------------------

def check_quality(fares: list[FareBrand]) -> list[str]:
    """Temel kalite kontrolleri; kullanıcıya gösterilecek uyarı listesi döner.

    Kontroller:
    - Eksik kayıt (fiyatsız / markasız satır)
    - Para birimi hatası (bilinmeyen kur -> USD çevrilemedi)
    - Duplicate kayıt (aynı CollDate + havayolu + OND + kabin + marka)
    - Tutarsız fiyat (aynı kabinde üst paketin alttan ucuz olması)
    """
    issues: list[str] = []
    seen: set[tuple[str, ...]] = set()

    for f in fares:
        rid = f"{f.airline} {f.origin}-{f.destination} {f.cabin}/{f.fare_brand}"
        if f.price is None:
            issues.append(f"Eksik fiyat: {rid}")
        if not f.fare_brand:
            issues.append(f"Eksik paket adı: {f.airline} {f.origin}-{f.destination}")
        if f.price is not None and getattr(f, "price_usd", None) is None:
            issues.append(f"Para birimi hatası ({f.currency or '?'}): {rid}")
        key = (getattr(f, "coll_date", ""), f.airline, f.origin,
               f.destination, f.cabin, f.fare_brand)
        if key in seen:
            issues.append(f"Duplicate kayıt: {rid}")
        seen.add(key)

    # Kabin içi fiyat sıralaması tutarlılığı
    groups: dict[tuple[str, ...], list[FareBrand]] = {}
    for f in fares:
        groups.setdefault(
            (getattr(f, "coll_date", ""), f.airline, f.origin, f.destination, f.cabin),
            [],
        ).append(f)
    for key, grp in groups.items():
        grp = sorted(grp, key=lambda x: x.package_order)
        for lo, hi in zip(grp, grp[1:]):
            if lo.price is not None and hi.price is not None and hi.price < lo.price:
                issues.append(
                    f"Tutarsız fiyat: {key[1]} {key[2]}-{key[3]} {key[4]} — "
                    f"{hi.fare_brand} ({hi.price}) < {lo.fare_brand} ({lo.price})"
                )

    for msg in issues:
        log.warning("KALİTE: %s", msg)
    return issues
