"""Web formuna girilen değerlerin doğruluğunu kontrol eden yardımcılar.

Havayolu arama formları girdiyi sık sık **dönüştürür** (örn. "IST" → "Istanbul
(IST)", "2026-08-01" → "01 Aug 2026"). Bu yüzden alanları oku-geri (`input_value`)
doğrularken **tam eşitlik değil, yansıma** aranır: alan boş kalmadıysa ve girilen
kod/tarih değeri alanda görünüyorsa giriş başarılı sayılır.

`input_matches` saf bir fonksiyondur (tarayıcı gerektirmez) — birim testlerle
kapsanır; async/sync scraper yollarının ikisi de bunu kullanır.
"""
from __future__ import annotations

import re


def _norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


# Ay numarası → alanda görülebilecek ay adı belirteçleri (İngilizce + Türkçe).
_MONTH_TOKENS: dict[int, set[str]] = {
    1: {"jan", "january", "oca", "ocak"},
    2: {"feb", "february", "şub", "sub", "şubat", "subat"},
    3: {"mar", "march", "mart"},
    4: {"apr", "april", "nis", "nisan"},
    5: {"may", "mayıs", "mayis"},
    6: {"jun", "june", "haz", "haziran"},
    7: {"jul", "july", "tem", "temmuz"},
    8: {"aug", "august", "ağu", "agu", "ağustos", "agustos"},
    9: {"sep", "sept", "september", "eyl", "eylül", "eylul"},
    10: {"oct", "october", "eki", "ekim"},
    11: {"nov", "november", "kas", "kasım", "kasim"},
    12: {"dec", "december", "ara", "aralık", "aralik"},
}


def _looks_like_date(value: str) -> bool:
    """Değer tarih gibi mi? (4 haneli yıl + en az bir ayraçla sayı kalıbı)"""
    return bool(re.search(r"\d{4}", value) and re.search(r"\d[\D]?\d", value))


def _date_reflected(expected: str, actual: str) -> bool:
    """Beklenen tarihin yıl/ay/gün parçaları alanda geçiyor mu?

    Ay sayısal (``08``) ya da metinsel (``Aug`` / ``Ağu``) olabilir; her iki
    biçim de kabul edilir. Böylece "2026-08-01" ↔ "01 Aug 2026" eşleşir ama
    "2026-09-01" eşleşmez (ay farklı)."""
    nums = [p for p in re.split(r"\D+", expected) if p]
    if not nums:
        return False
    year = next((p for p in nums if len(p) == 4), "")
    if year and year not in actual:
        return False

    actual_nums = {(p.lstrip("0") or "0") for p in re.split(r"\D+", actual) if p}
    actual_words = set(re.findall(r"[a-zğçşıöü]+", actual))
    for p in nums:
        if len(p) == 4:
            continue  # yıl zaten kontrol edildi
        pn = p.lstrip("0") or "0"
        if pn in actual_nums:
            continue
        month = int(pn) if pn.isdigit() else 0
        if 1 <= month <= 12 and (_MONTH_TOKENS[month] & actual_words):
            continue
        return False
    return True


def input_matches(expected: str, actual: str) -> bool:
    """Girilen değer form alanında doğru yansımış mı? (otomatik tamamlama toleranslı)

    - ``actual`` boşsa → ``False`` (alan boş kaldı, giriş başarısız).
    - ``expected`` boşsa → ``True`` (doğrulanacak bir şey yok).
    - Biri diğerini kapsıyorsa ya da kod çekirdeği (IST/LHR) alanda geçiyorsa → ``True``.
    - Tarih değerinde tüm sayısal parçalar alanda geçiyorsa → ``True`` (biçim farkı toleranslı).
    """
    e, a = _norm(expected), _norm(actual)
    if not a:
        return False
    if not e:
        return True
    if e in a or a in e:
        return True

    e_core = re.sub(r"[^a-z0-9]", "", e)
    a_core = re.sub(r"[^a-z0-9]", "", a)
    if e_core and e_core in a_core:
        return True

    if _looks_like_date(e) and _date_reflected(e, a):
        return True
    return False
