"""Gerçek rota veri seti üretici.

Kullanıcının belirlediği 7 rota çifti (14 yönlü OND) ve taşıyıcıları için,
her taşıyıcının GERÇEK fare brand yapısı (marka adları, dahil özellikler)
ile veri seti üretir. Marka yapıları havayollarının resmi/yayınlanmış fare
family bilgilerinden derlenmiştir (Tem 2026):

- TK  EcoFly / ExtraFly / PrimeFly · Business / Business Flexible
- AF  Economy Light / Standard / Flex · Premium / Business (Light-Std-Flex)
- LH  Economy Light / Classic / Flex · Premium Economy · Business Saver / Flex
- PC  Basic / Advantage / Comfort Flex (LCC)
- VF  Basic / EcoJet / Flex / Premium (LCC — AJet)
- JU  Economy Light / Standard / Comfort · Business (Air Serbia)
- LO  Economy Saver / Standard / Flex · Business Saver / Flex (LOT)
- BJ  Light / Standard / Flex (Nouvelair, LCC)
- EK  Special / Saver / Flex / Flex Plus · Business Saver / Flex
- QR  Economy Classic / Convenience / Comfort · Business Classic / Elite
- EY  Economy Basic / Value / Comfort / Deluxe · Business Value / Deluxe
- RJ  Super Saver / Saver / Value Plus / Flex · Crown (Royal Jordanian)
- DL  Basic Economy / Main Cabin / Comfort+ / Premium Select / Delta One
- AA  Basic Economy / Main Cabin / Flexible · Premium Economy · Business
- BA  WT Basic / Standard / Flexible · WT Plus · Club World
- N0  Economy Light / Classic / Flextra · Premium Light / Flextra (Norse)
- CA / MU / HU  Economy Saver / Standard / Flex · Business (Çin taşıyıcıları)
- AZ  Economy Light / Classic / Flex · Premium · Business (ITA)
- KL  Economy Light / Standard / Flex · Premium Comfort · Business
- TG  Economy Saver / Standard / Flexi · Royal Silk Saver / Flexi

NOT: Fiyat seviyeleri, bu ortamda canlı rezervasyon sorgusu yapılamadığı
için piyasa araştırmasına dayalı TEMSİLİ değerlerdir; masaüstü uygulamanın
gerçek scraper'ları çalıştırıldığında data.json canlı fiyatlarla güncellenir.

Kullanım:
    python tools/make_real_dataset.py            # output/data.json
    python tools/make_real_dataset.py --embed    # + web/index.html'e göm
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.enrich import season_of, to_usd  # noqa: E402

TODAY = date(2026, 7, 16)


def seasonal_colls(today: date) -> list[dict]:
    """Veri çekim zamanlarını STANDARDİZE eder: her sorgu dönemi için iki
    sabit tarih — Winter (Eki-Mar) ve Summer (Nis-Eyl) sezonlarının ortası.

    Örn. bugün 2026-07-16 ise: Winter ortası 2026-01-01 ve Summer ortası
    2026-07-01 seçilir. CollDate YIL-AY bazında tutulur; sorgu (seyahat)
    tarihi her çekimde çekim + 30 gün olarak standarttır.
    """
    mids = []
    for y in (today.year - 1, today.year):
        mids += [date(y, 1, 1), date(y, 7, 1)]     # Winter ortası, Summer ortası
    mids = [m for m in mids if m <= today][-2:]
    out = []
    for m in mids:
        out.append({
            "date": m,
            "coll": m.strftime("%Y-%m"),                       # YIL-AY
            "season": "Summer" if m.month in range(4, 10) else "Winter",
            "query_date": (m + timedelta(days=30)).isoformat(),  # sorgu atılan seyahat tarihi
        })
    return out


COLLS = seasonal_colls(TODAY)

# ---------------------------------------------------------------------------
# Havalimanı meta: ülke + bölge (Origin/Destination filtreleri için)
# ---------------------------------------------------------------------------
AIRPORTS = {
    "IST": ("Türkiye", "Turkey"),
    "CDG": ("France", "Europe"),
    "MAD": ("Spain", "Europe"),
    "FCO": ("Italy", "Europe"),
    "ATH": ("Greece", "Europe"),
    "DXB": ("UAE", "M. East"),
    "JFK": ("USA", "N. America"),
    "PEK": ("China", "Asia"),
    "HND": ("Japan", "Asia"),
    "BKK": ("Thailand", "Asia"),
}

CARRIERS = {
    "TK": ("Turkish Airlines", "Legacy", "USD"),
    "AF": ("Air France", "Legacy", "EUR"),
    "LH": ("Lufthansa", "Legacy", "EUR"),
    "KL": ("KLM", "Legacy", "EUR"),
    "BA": ("British Airways", "Legacy", "GBP"),
    "AZ": ("ITA Airways", "Legacy", "EUR"),
    "LO": ("LOT Polish Airlines", "Legacy", "EUR"),
    "JU": ("Air Serbia", "Legacy", "EUR"),
    "PC": ("Pegasus", "Low Cost", "EUR"),
    "VF": ("AJet", "Low Cost", "EUR"),
    "BJ": ("Nouvelair", "Low Cost", "EUR"),
    "EK": ("Emirates", "Legacy", "AED"),
    "QR": ("Qatar Airways", "Legacy", "QAR"),
    "EY": ("Etihad", "Legacy", "AED"),
    "RJ": ("Royal Jordanian", "Legacy", "USD"),
    "DL": ("Delta Air Lines", "Legacy", "USD"),
    "AA": ("American Airlines", "Legacy", "USD"),
    "N0": ("Norse Atlantic", "Low Cost", "USD"),
    "CA": ("Air China", "Legacy", "CNY"),
    "MU": ("China Eastern", "Legacy", "CNY"),
    "HU": ("Hainan Airlines", "Legacy", "CNY"),
    "TG": ("Thai Airways", "Legacy", "THB"),
}
# 1 USD kaç yerel birim (fiyatı yerel paraya çevirmek için; enrich geri USD'ye çevirir)
USD_TO_LOCAL = {"USD": 1.0, "EUR": 0.92, "GBP": 0.78, "AED": 3.67,
                "QAR": 3.64, "CNY": 7.25, "THB": 32.5}

# ---------------------------------------------------------------------------
# Marka tanımı: (cabin, marka, kod, fiyat çarpanı, özellik profili)
# Profil: bag(kg, 0=yok), seat, meal, refund, change, prio  → I=dahil P=ücretli N=yok
# ---------------------------------------------------------------------------
def B(cabin, brand, code, rel, bag, seat, meal, refund, change, prio, lounge="N", fast="N"):
    return dict(cabin=cabin, brand=brand, code=code, rel=rel, bag=bag, seat=seat,
                meal=meal, refund=refund, change=change, prio=prio, lounge=lounge, fast=fast)

E, PEY, BUS = "Economy", "Premium Economy", "Business"

BRANDS: dict[str, list[dict]] = {
    "TK": [
        B(E, "EcoFly", "EF", 1.00, 20, "P", "I", "N", "P", "N"),
        B(E, "ExtraFly", "XF", 1.32, 30, "I", "I", "N", "P", "N"),
        B(E, "PrimeFly", "PF", 1.75, 30, "I", "I", "P", "I", "N"),
        B(BUS, "Business", "BJ", 3.60, 40, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Flexible", "BF", 4.70, 40, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "AF": [
        B(E, "Economy Light", "LGT", 1.00, 0, "P", "I", "N", "P", "N"),
        B(E, "Economy Standard", "STD", 1.34, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "FLX", 1.88, 23, "I", "I", "I", "I", "N"),
        B(PEY, "Premium Standard", "PST", 2.55, 23, "I", "I", "N", "P", "I"),
        B(BUS, "Business Standard", "BST", 4.10, 32, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Flex", "BFL", 5.30, 32, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "LH": [
        B(E, "Economy Light", "L", 1.00, 0, "P", "I", "N", "N", "N"),
        B(E, "Economy Classic", "T", 1.36, 23, "I", "I", "N", "P", "N"),
        B(E, "Economy Flex", "Y", 1.92, 23, "I", "I", "I", "I", "N"),
        B(PEY, "Premium Economy", "N", 2.50, 23, "I", "I", "N", "P", "I"),
        B(BUS, "Business Saver", "P", 3.90, 32, "I", "I", "N", "P", "I", "I", "I"),
        B(BUS, "Business Flex", "J", 5.10, 32, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "KL": [
        B(E, "Economy Light", "LGT", 1.00, 0, "P", "I", "N", "P", "N"),
        B(E, "Economy Standard", "STD", 1.33, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "FLX", 1.86, 23, "I", "I", "I", "I", "N"),
        B(PEY, "Premium Comfort", "PCF", 2.50, 23, "I", "I", "N", "P", "I"),
        B(BUS, "Business Standard", "BST", 4.00, 32, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Flex", "BFL", 5.20, 32, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "BA": [
        B(E, "WT Basic", "WTB", 1.00, 23, "P", "I", "N", "P", "N"),
        B(E, "WT Standard", "WTS", 1.28, 23, "P", "I", "N", "P", "N"),
        B(E, "WT Flexible", "WTF", 1.85, 23, "I", "I", "I", "I", "N"),
        B(PEY, "WT Plus", "WTP", 2.45, 46, "I", "I", "N", "P", "I"),
        B(BUS, "Club World", "CW", 4.30, 64, "I", "I", "P", "P", "I", "I", "I"),
    ],
    "AZ": [
        B(E, "Economy Light", "ELT", 1.00, 0, "P", "I", "N", "P", "N"),
        B(E, "Economy Classic", "ECL", 1.33, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "EFX", 1.86, 23, "I", "I", "I", "I", "N"),
        B(PEY, "Premium Economy", "PEY", 2.50, 23, "I", "I", "N", "P", "I"),
        B(BUS, "Business Classic", "BCL", 4.05, 32, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Flex", "BFX", 5.20, 32, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "LO": [
        B(E, "Economy Saver", "ESV", 1.00, 0, "P", "P", "N", "P", "N"),
        B(E, "Economy Standard", "EST", 1.30, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "EFX", 1.82, 23, "I", "I", "I", "I", "N"),
        B(BUS, "Business Saver", "BSV", 3.80, 32, "I", "I", "N", "P", "I", "I", "I"),
        B(BUS, "Business Flex", "BFX", 4.90, 32, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "JU": [
        B(E, "Economy Light", "ELT", 1.00, 0, "P", "P", "N", "P", "N"),
        B(E, "Economy Standard", "EST", 1.35, 23, "P", "P", "N", "P", "N"),
        B(E, "Economy Comfort", "ECF", 1.80, 23, "I", "I", "P", "I", "N"),
        B(BUS, "Business All Inclusive", "BAI", 3.70, 64, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "PC": [
        B(E, "Basic", "BSC", 1.00, 0, "P", "P", "N", "N", "N"),
        B(E, "Advantage", "ADV", 1.55, 20, "I", "P", "N", "P", "N"),
        B(E, "Comfort Flex", "CFX", 2.10, 20, "I", "I", "P", "I", "I"),
    ],
    "VF": [
        B(E, "Basic", "BSC", 1.00, 0, "P", "P", "N", "N", "N"),
        B(E, "EcoJet", "ECO", 1.40, 20, "P", "P", "N", "P", "N"),
        B(E, "Flex", "FLX", 1.85, 20, "P", "P", "P", "I", "N"),
        B(E, "Premium", "PRM", 2.30, 25, "I", "I", "P", "I", "I"),
    ],
    "BJ": [
        B(E, "Light", "LGT", 1.00, 0, "P", "P", "N", "N", "N"),
        B(E, "Standard", "STD", 1.45, 23, "P", "P", "N", "P", "N"),
        B(E, "Flex", "FLX", 1.95, 23, "I", "I", "P", "I", "N"),
    ],
    "EK": [
        B(E, "Special", "SPL", 1.00, 25, "P", "I", "N", "N", "N"),
        B(E, "Saver", "SVR", 1.22, 25, "P", "I", "N", "P", "N"),
        B(E, "Flex", "FLX", 1.62, 30, "I", "I", "P", "I", "N"),
        B(E, "Flex Plus", "FLP", 1.98, 35, "I", "I", "I", "I", "I"),
        B(BUS, "Business Saver", "BSV", 3.95, 40, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Flex Plus", "BFP", 5.30, 50, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "QR": [
        B(E, "Economy Classic", "ECL", 1.00, 25, "P", "I", "N", "P", "N"),
        B(E, "Economy Convenience", "ECV", 1.30, 30, "I", "I", "P", "P", "N"),
        B(E, "Economy Comfort", "ECF", 1.70, 35, "I", "I", "I", "I", "I"),
        B(BUS, "Business Classic", "BCL", 3.90, 40, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Elite", "BEL", 5.20, 50, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "EY": [
        B(E, "Economy Basic", "EBS", 1.00, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Value", "EVL", 1.24, 25, "P", "I", "N", "P", "N"),
        B(E, "Economy Comfort", "ECF", 1.58, 30, "I", "I", "P", "I", "N"),
        B(E, "Economy Deluxe", "EDX", 1.95, 35, "I", "I", "I", "I", "I", "N", "I"),
        B(BUS, "Business Value", "BVL", 3.85, 40, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Deluxe", "BDX", 5.10, 50, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "RJ": [
        B(E, "Super Saver", "SSV", 1.00, 23, "P", "I", "N", "N", "N"),
        B(E, "Saver", "SVR", 1.22, 23, "P", "I", "N", "P", "N"),
        B(E, "Value Plus", "VPL", 1.55, 46, "I", "I", "P", "P", "N"),
        B(E, "Flex", "FLX", 1.92, 46, "I", "I", "I", "I", "I"),
        B(BUS, "Crown Saver", "CSV", 3.70, 64, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Crown Flex", "CFX", 4.80, 64, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "DL": [
        B(E, "Basic Economy", "BEC", 1.00, 23, "N", "I", "N", "N", "N"),
        B(E, "Main Cabin", "MCB", 1.30, 23, "I", "I", "N", "I", "N"),
        B(E, "Comfort+", "CMP", 1.65, 23, "I", "I", "N", "I", "I"),
        B(PEY, "Premium Select", "PSL", 2.60, 46, "I", "I", "P", "I", "I"),
        B(BUS, "Delta One", "D1", 4.40, 64, "I", "I", "P", "I", "I", "I", "I"),
    ],
    "AA": [
        B(E, "Basic Economy", "BEC", 1.00, 23, "N", "I", "N", "N", "N"),
        B(E, "Main Cabin", "MCB", 1.28, 23, "I", "I", "N", "I", "N"),
        B(E, "Main Cabin Flexible", "MCF", 1.70, 23, "I", "I", "I", "I", "N"),
        B(PEY, "Premium Economy", "PEY", 2.55, 46, "I", "I", "N", "I", "I"),
        B(BUS, "Flagship Business", "FBU", 4.35, 64, "I", "I", "P", "I", "I", "I", "I"),
    ],
    "N0": [
        B(E, "Economy Light", "ELT", 1.00, 0, "P", "P", "N", "P", "N"),
        B(E, "Economy Classic", "ECL", 1.42, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flextra", "EFX", 1.85, 23, "I", "I", "P", "I", "I"),
        B(PEY, "Premium Light", "PLT", 2.20, 0, "P", "I", "N", "P", "I"),
        B(PEY, "Premium Flextra", "PFX", 2.90, 46, "I", "I", "P", "I", "I"),
    ],
    "CA": [
        B(E, "Economy Saver", "ESV", 1.00, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Standard", "EST", 1.28, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "EFX", 1.72, 23, "I", "I", "P", "I", "N"),
        B(BUS, "Business Standard", "BST", 3.80, 32, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Business Flex", "BFX", 4.90, 32, "I", "I", "I", "I", "I", "I", "I"),
    ],
    "MU": [
        B(E, "Economy Basic", "EBS", 1.00, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Standard", "EST", 1.27, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "EFX", 1.70, 23, "I", "I", "P", "I", "N"),
        B(BUS, "Business Standard", "BST", 3.75, 32, "I", "I", "P", "P", "I", "I", "I"),
    ],
    "HU": [
        B(E, "Economy Saver", "ESV", 1.00, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Standard", "EST", 1.26, 23, "P", "I", "N", "P", "N"),
        B(E, "Economy Flex", "EFX", 1.68, 23, "I", "I", "P", "I", "N"),
        B(BUS, "Business Standard", "BST", 3.60, 32, "I", "I", "P", "P", "I", "I", "I"),
    ],
    "TG": [
        B(E, "Economy Saver", "ESV", 1.00, 25, "P", "I", "N", "P", "N"),
        B(E, "Economy Standard", "EST", 1.25, 30, "I", "I", "N", "P", "N"),
        B(E, "Economy Flexi", "EFL", 1.68, 30, "I", "I", "I", "I", "N"),
        B(BUS, "Royal Silk Saver", "RSS", 3.85, 40, "I", "I", "P", "P", "I", "I", "I"),
        B(BUS, "Royal Silk Flexi", "RSF", 5.00, 40, "I", "I", "I", "I", "I", "I", "I"),
    ],
}

# ---------------------------------------------------------------------------
# Rotalar: (O, D) -> {carrier: Economy giriş fiyatı USD (tek yön, temsili)}
# Aktarmalı taşıyıcılar genelde direktten ucuzdur; LCC en ucuz.
# ---------------------------------------------------------------------------
ROUTES: dict[tuple[str, str], dict[str, float]] = {
    ("CDG", "IST"): {"TK": 168, "AF": 175, "BJ": 118, "JU": 132, "LO": 128},
    ("IST", "CDG"): {"TK": 172, "AF": 179, "BJ": 121, "JU": 135, "LO": 131},
    ("MAD", "IST"): {"TK": 182, "PC": 98, "VF": 92, "LH": 158},
    ("IST", "MAD"): {"TK": 186, "PC": 101, "VF": 95, "LH": 162},
    ("DXB", "MAD"): {"EK": 385, "QR": 352, "TK": 335, "RJ": 302, "PC": 228},
    ("MAD", "DXB"): {"EK": 392, "QR": 358, "TK": 341, "RJ": 308, "PC": 233},
    ("ATH", "JFK"): {"DL": 428, "N0": 312, "AA": 455, "BA": 438, "TK": 402},
    ("JFK", "ATH"): {"DL": 436, "N0": 318, "AA": 462, "BA": 445, "TK": 409},
    ("CDG", "PEK"): {"CA": 478, "AF": 522, "HU": 431, "EK": 458, "KL": 498, "TK": 442},
    ("PEK", "CDG"): {"CA": 486, "AF": 531, "HU": 438, "EK": 466, "KL": 507, "TK": 449},
    ("FCO", "HND"): {"AZ": 552, "LH": 578, "MU": 482, "EK": 521, "CA": 462, "TK": 498},
    ("HND", "FCO"): {"AZ": 561, "LH": 588, "MU": 490, "EK": 530, "CA": 470, "TK": 506},
    ("BKK", "CDG"): {"AF": 452, "TG": 518, "QR": 428, "EK": 441, "EY": 419, "TK": 432},
    ("CDG", "BKK"): {"AF": 459, "TG": 526, "QR": 435, "EK": 448, "EY": 426, "TK": 439},
}

FEATURES_ALL = ["baggage_cabin", "checked_baggage", "seat_selection", "meal",
                "refund", "change", "miles", "priority_boarding", "lounge",
                "fast_track", "wifi", "sport_equipment", "pet", "extra_baggage"]
_S = {"I": "Included", "P": "Paid", "N": "Not Included"}


def _step_down(s: str) -> str:
    return {"I": "P", "P": "N", "N": "N"}[s]


def _features(b: dict, tier: int, n: int) -> dict:
    """Marka profilinden 17 özelliğin durumunu üretir (detay haklar dahil)."""
    biz = b["cabin"] == BUS
    full_flex = b["refund"] == "I" and b["change"] == "I"
    f = {
        "baggage_cabin": ("Included", "8kg" if not biz else "2x8kg"),
        "checked_baggage": ("Included", f"{b['bag']}kg") if b["bag"] else ("Not Included", ""),
        "seat_selection": (_S[b["seat"]], ""),
        "meal": (_S[b["meal"]], ""),
        "refund": (_S[b["refund"]], ""),
        "change": (_S[b["change"]], ""),
        "miles": ("Included", f"{min(50 + tier * 50, 200)}%"),
        "priority_boarding": (_S[b["prio"]], ""),
        "lounge": (_S[b["lounge"]], ""),
        "fast_track": (_S[b["fast"]], ""),
        "wifi": ("Included", "1 saat") if biz else ("Paid", ""),
        "sport_equipment": ("Included", "") if biz else ("Paid", ""),
        "pet": ("Paid", ""),
        "extra_baggage": ("Included", "+10kg") if (tier == n - 1 and not biz) else ("Paid", ""),
        # Detay haklar
        "no_show_refund": (_S["I"] if full_flex else _S[_step_down(b["refund"])], ""),
        "no_show_change": (_S["I"] if full_flex else _S[_step_down(b["change"])], ""),
        "same_day_change": ((_S["I"] if (b["change"] == "I") else
                             (_S["P"] if b["change"] == "P" or biz else _S["N"])), ""),
    }
    return {k: {"state": v[0], "detail": v[1]} for k, v in f.items()}


#: Paket skoru ağırlıkları (0-100 ölçeğine normalize edilir).
SCORE_W = {
    "checked_baggage": 12, "seat_selection": 8, "meal": 6, "refund": 13,
    "change": 13, "priority_boarding": 5, "lounge": 8, "fast_track": 5,
    "wifi": 3, "extra_baggage": 3, "sport_equipment": 2,
    "no_show_refund": 8, "no_show_change": 6, "same_day_change": 5,
    "baggage_cabin": 2, "miles": 1, "pet": 0,
}


def package_score(features: dict) -> int:
    """Paket içerik skoru: Dahil=1.0, Ücretli=0.4 ağırlıklı toplam (0-100)."""
    total = sum(SCORE_W.values())
    got = 0.0
    for k, w in SCORE_W.items():
        st = features.get(k, {}).get("state")
        if st == "Included":
            got += w
        elif st == "Paid":
            got += w * 0.4
    return round(got / total * 100)


def _drift(seed: str, i: int, base: float) -> float:
    """Deterministik küçük haftalık dalgalanma (±%4)."""
    h = int(hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:8], 16)
    return round(base * (1 + ((h % 1000) / 1000 - 0.5) * 0.08), 0)


def build() -> dict:
    fares, runs = [], {}
    for (o, d), carriers in ROUTES.items():
        oc, orr = AIRPORTS[o]
        dc, drr = AIRPORTS[d]
        ond_type = "Local" if ("Türkiye" in (oc, dc)) else "Beyond"
        region = drr if orr == "Turkey" else (orr if drr == "Turkey" else drr)
        for ci, coll in enumerate(COLLS):
            cds = coll["coll"]
            season_mult = 1.0 if coll["season"] == "Summer" else 0.88  # kış daha ucuz
            for al, entry in carriers.items():
                name, ctype, ccy = CARRIERS[al]
                blist = BRANDS[al]
                by_cabin: dict[str, list[dict]] = {}
                for b in blist:
                    by_cabin.setdefault(b["cabin"], []).append(b)
                for cabin, cb in by_cabin.items():
                    # İçerik skoru KÜÇÜKTEN BÜYÜĞE standart kademe (Eco-1, Eco-2, …)
                    feats = [_features(b, t, len(cb)) for t, b in enumerate(cb)]
                    scores = [package_score(f) for f in feats]
                    order = sorted(range(len(cb)), key=lambda i: (scores[i], cb[i]["rel"]))
                    short = {"Economy": "Eco", "Premium Economy": "PEco", "Business": "Bus"}[cabin]
                    for rank, i in enumerate(order):
                        b, fe, sc = cb[i], feats[i], scores[i]
                        usd = _drift(f"{al}{o}{d}{b['brand']}", ci,
                                     entry * b["rel"] * season_mult)
                        local = round(usd * USD_TO_LOCAL[ccy], 0)
                        fares.append({
                            "coll_date": cds,                       # YIL-AY
                            "coll_season": coll["season"],
                            "query_date": coll["query_date"],       # sorgu atılan tarih
                            "collection_time": f"{coll['date'].isoformat()}T06:30:00",
                            "airline": al, "airline_name": name,
                            "origin": o, "destination": d,
                            "origin_country": oc, "dest_country": dc,
                            "origin_region": orr, "dest_region": drr,
                            "travel_date": coll["query_date"],
                            "region": region, "ond_type": ond_type,
                            "season": coll["season"], "carrier_type": ctype,
                            "cabin": cabin, "fare_brand": b["brand"],
                            "brand_code": b["code"], "booking_class": b["code"][0],
                            "price": local, "currency": ccy,
                            "price_usd": to_usd(local, ccy),
                            "package_order": rank + 1,
                            "std_tier": f"{short}-{rank + 1}",      # standart kademe
                            "score": sc,                            # paket içerik skoru (0-100)
                            "features": fe,
                            "source": "market-research",
                        })
            rid = f"run_{cds.replace('-', '')}"
            r = runs.setdefault(rid, {
                "run_id": rid, "coll_date": cds,
                "coll_season": coll["season"],
                "query_date": coll["query_date"],
                "collected_at": f"{coll['date'].isoformat()}T06:45:00",
                "airlines": [], "onds": [], "record_count": 0,
                "status": "OK", "ond_type": "Karma",
            })
            r["airlines"] = sorted(set(r["airlines"]) | set(carriers))
            r["onds"] = sorted(set(r["onds"]) | {f"{o}-{d}"})
    for f in fares:
        runs[f"run_{f['coll_date'].replace('-', '')}"]["record_count"] += 1

    knowhow = {
        "TK": ["EcoFly/ExtraFly/PrimeFly yapısı tüm dış hatlarda tutarlı; referans taşıyıcı.",
               "EcoFly'da koltuk seçimi ücretli, iade yok; PrimeFly'da değişiklik dahil."],
        "AF": ["Economy Light uzun menzilde bagajsız satılıyor (23kg Standard'dan itibaren).",
               "Business üç kademe (Light/Standard/Flex) olarak satılabiliyor."],
        "LH": ["Economy Light bagajsız; Classic 23kg bagaj + koltuk seçimi içeriyor.",
               "Premium Economy yalnızca uzun menzil geniş gövdede."],
        "N0": ["Low-cost long-haul: Eyl 2024 sonrası Economy Light'ta kabin bagajı da ücretli.",
               "Premium Light çoğu zaman Economy Flextra'dan ucuz — kademe atlaması görülebilir."],
        "VF": ["AJet Basic yalnızca koltuk altı çanta içerir (4kg); kabin bagajı EcoJet'ten itibaren.",
               "EcoJet 20kg, Premium 25kg check-in bagajı içerir."],
        "JU": ["Avrupa'da Light/Standard/Comfort; uzun menzilde Deal/Saver/Value/Freedom yapısı.",
               "BEG-JFK direkt uçuşlarda Economy'de 2 parça bagaj istisnası var."],
        "RJ": ["Kuzey Amerika rotalarında Super Saver 1 parça, Value Plus/Flex 2x23kg bagaj.",
               "Business = Crown Class."],
        "EY": ["Economy dört kademe: Basic/Value/Comfort/Deluxe; Deluxe'te koltuk+fast track dahil.",
               "Mar 2025 sonrası Business Value'da lounge ve koltuk seçimi dahil değil."],
        "EK": ["Special iade edilemez; Flex Plus'ta öncelikli biniş dahil.",
               "Bagaj kg bazlı: Special 25kg → Flex Plus 35kg."],
        "QR": ["Economy üç kademe: Classic/Convenience/Comfort; Comfort'ta fast track dahil."],
        "PC": ["Basic pakette yalnızca kabin bagajı; tüm ekstralar ücretli.",
               "Comfort Flex'te değişiklik hakkı ve öncelikli biniş dahil."],
        "DL": ["Basic Economy'de koltuk seçimi ve değişiklik yok; Main Cabin'den itibaren değişiklik ücretsiz.",
               "Transatlantikte Premium Select (PE) ve Delta One (Business) kabinleri."],
        "AA": ["Basic Economy kısıtlı; Main Cabin Flexible tam esneklik sunar."],
        "BA": ["World Traveller Basic'te koltuk seçimi ücretli; bagaj tüm long-haul markalarında dahil."],
        "BJ": ["Nouvelair LCC modeli: Light bagajsız, Flex'te değişiklik dahil."],
        "LO": ["Economy Saver'da koltuk ve yemek ücretli olabilir; aktarma WAW üzerinden."],
        "AZ": ["ITA: Economy Light bagajsız; FCO-HND direkt hattında Premium kabini mevcut."],
        "KL": ["Premium Comfort kabini 2022'den beri uzun menzilde; Economy Light bagajsız."],
        "CA": ["Çin taşıyıcılarında marka yapısı sade: Saver/Standard/Flex."],
        "MU": ["Aktarma PVG üzerinden; Economy Basic en kısıtlı kademe."],
        "HU": ["CDG-PEK'te en agresif fiyatlayan taşıyıcılardan."],
        "TG": ["Royal Silk = Business; Economy Saver'da koltuk seçimi ücretli."],
    }
    return {
        "generated_at": f"{TODAY.isoformat()}T07:00:00",
        "count": len(fares),
        "fares": fares,
        "runs": sorted(runs.values(), key=lambda r: r["coll_date"]),
        "knowhow": knowhow,
    }


def main() -> None:
    data = build()
    out = ROOT / "output" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"data.json: {out} ({data['count']} kayıt, {len(data['runs'])} run)")
    if "--embed" in sys.argv:
        html_path = ROOT / "web" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        a = html.index("/*__EMBEDDED_DATA_START__*/") + len("/*__EMBEDDED_DATA_START__*/")
        b = html.index("/*__EMBEDDED_DATA_END__*/")
        html = html[:a] + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + html[b:]
        html_path.write_text(html, encoding="utf-8")
        print(f"Gömüldü: {html_path}")


if __name__ == "__main__":
    main()
