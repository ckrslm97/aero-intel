"""Demo geçmiş verisi üretici.

HTML panelinin zaman serisi özelliklerini (Line Chart, Paket Evrimi,
akıllı uyarılar, Archive) gerçekçi biçimde gösterebilmek için birden çok
CollDate'e yayılmış örnek veri üretir:

- Local OND'ler HAFTALIK, Beyond OND'ler AYLIK çekilmiş gibi simüle edilir
  (frekans planıyla birebir uyumlu).
- Karma para birimleri (EUR/AED/SGD/TRY/USD) üretilir; USD dönüşümü
  core.enrich üzerinden yapılır.
- Bilerek enjekte edilen olaylar:
    * LH  : 2026-06-25'te yeni "Economy Green" paketi (yeni paket ⭐)
    * PC  : 2026-06-18 sonrası "Advantage" paketi kaldırılır (❗)
    * EK  : 2026-07-02'de IST-DXB Business'ta ani fiyat sıçraması (❗)
    * AF  : 2026-07-16'da Economy paketlerinde kampanya indirimi (⭐)

Kullanım:
    python tools/make_demo_history.py            # output/data.json üretir
    python tools/make_demo_history.py --embed    # + web/index.html içine gömer
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.enrich import (  # noqa: E402
    carrier_type_of, ond_type_of, region_of, season_of, to_usd,
)

TODAY = date(2026, 7, 16)

# ---------------------------------------------------------------------------
# Senaryo tanımı
# ---------------------------------------------------------------------------

CARRIER_NAMES = {
    "TK": "Turkish Airlines", "LH": "Lufthansa", "AF": "Air France",
    "EK": "Emirates", "SQ": "Singapore Airlines", "PC": "Pegasus",
}
CARRIER_CCY = {"TK": "USD", "LH": "EUR", "AF": "EUR", "EK": "AED", "SQ": "SGD", "PC": "TRY"}
# AED/SGD/TRY birim fiyat çarpanları (yerel para cinsinden anlamlı büyüklük)
CCY_SCALE = {"USD": 1.0, "EUR": 0.92, "AED": 3.67, "SGD": 1.34, "TRY": 41.0}

# (origin, dest) -> uçuran taşıyıcılar. TK olabildiğince her yerde (referans).
ROUTES: dict[tuple[str, str], list[str]] = {
    ("IST", "FRA"): ["TK", "LH", "PC"],
    ("IST", "CDG"): ["TK", "AF", "PC"],
    ("IST", "LHR"): ["TK", "LH"],
    ("IST", "DXB"): ["TK", "EK", "PC"],
    ("IST", "JFK"): ["TK", "LH"],
    ("FRA", "JFK"): ["LH"],          # Beyond — TK yok (karşılaştırmada boş kalır)
    ("CDG", "SIN"): ["AF", "SQ", "TK"],
    ("LHR", "DXB"): ["EK", "TK"],
}
LONG_HAUL = {("IST", "JFK"), ("FRA", "JFK"), ("CDG", "SIN"), ("LHR", "DXB")}

# Taşıyıcıya göre paket şablonları (USD taban, düşükten yükseğe)
BRANDS: dict[str, list[dict]] = {
    "TK": [
        {"cabin": "Economy", "brand": "EcoFly", "code": "EF", "base": 170},
        {"cabin": "Economy", "brand": "ExtraFly", "code": "XF", "base": 235},
        {"cabin": "Economy", "brand": "PrimeFly", "code": "PF", "base": 320},
        {"cabin": "Business", "brand": "Business", "code": "BJ", "base": 615},
        {"cabin": "Business", "brand": "Business Flexible", "code": "BF", "base": 820},
    ],
    "LH": [
        {"cabin": "Economy", "brand": "Economy Light", "code": "L", "base": 185},
        {"cabin": "Economy", "brand": "Economy Classic", "code": "T", "base": 265},
        {"cabin": "Economy", "brand": "Economy Flex", "code": "Y", "base": 375},
        {"cabin": "Premium Economy", "brand": "Premium Economy", "code": "N", "base": 430, "long_only": True},
        {"cabin": "Business", "brand": "Business Basic", "code": "P", "base": 640},
        {"cabin": "Business", "brand": "Business Flex", "code": "J", "base": 890},
    ],
    "AF": [
        {"cabin": "Economy", "brand": "Economy Light", "code": "LGT", "base": 180},
        {"cabin": "Economy", "brand": "Economy Standard", "code": "STD", "base": 255},
        {"cabin": "Economy", "brand": "Economy Flex", "code": "FLX", "base": 360},
        {"cabin": "Premium Economy", "brand": "Premium Standard", "code": "PST", "base": 445, "long_only": True},
        {"cabin": "Business", "brand": "Business Standard", "code": "BST", "base": 660},
        {"cabin": "Business", "brand": "Business Flex", "code": "BFL", "base": 905},
    ],
    "EK": [
        {"cabin": "Economy", "brand": "Special", "code": "SPL", "base": 210},
        {"cabin": "Economy", "brand": "Saver", "code": "SVR", "base": 275},
        {"cabin": "Economy", "brand": "Flex", "code": "FLX", "base": 385},
        {"cabin": "Economy", "brand": "Flex Plus", "code": "FLP", "base": 470},
        {"cabin": "Business", "brand": "Business Saver", "code": "BSV", "base": 980},
        {"cabin": "Business", "brand": "Business Flex", "code": "BFX", "base": 1290},
    ],
    "SQ": [
        {"cabin": "Economy", "brand": "Economy Lite", "code": "ELT", "base": 230},
        {"cabin": "Economy", "brand": "Economy Value", "code": "EVL", "base": 300},
        {"cabin": "Economy", "brand": "Economy Standard", "code": "EST", "base": 380},
        {"cabin": "Premium Economy", "brand": "Premium Economy", "code": "PEY", "base": 520, "long_only": True},
        {"cabin": "Business", "brand": "Business Standard", "code": "BST", "base": 1150},
    ],
    "PC": [
        {"cabin": "Economy", "brand": "Basic", "code": "BSC", "base": 95},
        {"cabin": "Economy", "brand": "Advantage", "code": "ADV", "base": 150},   # 06-18 sonrası kaldırılır
        {"cabin": "Economy", "brand": "Comfort Flex", "code": "CFX", "base": 205},
    ],
}

# Özellik merdiveni: kademe (0..n) büyüdükçe daha çok özellik dahil olur.
FEATURES = ["baggage_cabin", "checked_baggage", "seat_selection", "meal",
            "refund", "change", "miles", "priority_boarding", "lounge",
            "fast_track", "wifi", "sport_equipment", "pet", "extra_baggage"]


def _feature_state(feature: str, tier: int, n_tiers: int, cabin: str) -> dict:
    """Kademeye ve kabine göre gerçekçi özellik durumu üretir."""
    top = tier >= n_tiers - 1
    biz = cabin == "Business"
    prem = cabin == "Premium Economy"
    inc, paid, no = "Included", "Paid", "Not Included"
    table = {
        "baggage_cabin": (inc, "8kg"),
        "checked_baggage": (inc, "30kg") if biz else ((inc, "23kg") if tier >= 1 or prem else (no, "")),
        "seat_selection": (inc, "") if tier >= 1 or biz else (paid, ""),
        "meal": (inc, "") if biz or prem or tier >= 1 else (paid, ""),
        "refund": (inc, "") if top else ((paid, "") if tier >= 1 else (no, "")),
        "change": (inc, "") if top else ((paid, "") if tier >= 1 or biz else (no, "")),
        "miles": (inc, f"{min(50 + tier * 50, 200)}%"),
        "priority_boarding": (inc, "") if biz or top else (no, ""),
        "lounge": (inc, "") if biz else (no, ""),
        "fast_track": (inc, "") if biz else ((paid, "") if top else (no, "")),
        "wifi": (inc, "1 saat") if biz else (paid, ""),
        "sport_equipment": (paid, "") if not biz else (inc, ""),
        "pet": (paid, ""),
        "extra_baggage": (paid, "") if not top else (inc, "+10kg"),
    }
    state, detail = table[feature]
    return {"state": state, "detail": detail}


def _drift(seed: str, week_idx: int, base: float) -> float:
    """Deterministik, yumuşak haftalık fiyat sürüklenmesi (±%8 bandı)."""
    h = int(hashlib.sha256(f"{seed}:{week_idx}".encode()).hexdigest()[:8], 16)
    wave = ((h % 1000) / 1000 - 0.5) * 0.10          # ±%5 gürültü
    trend = 0.008 * week_idx                          # hafif yaz artışı
    return round(base * (1 + trend + wave), 0)


def _long_haul_mult(route: tuple[str, str]) -> float:
    return 2.6 if route in LONG_HAUL else 1.0


def build() -> dict:
    local_dates = [TODAY - timedelta(weeks=w) for w in range(7, -1, -1)]      # 8 hafta
    beyond_dates = [TODAY - timedelta(days=30 * m) for m in range(2, -1, -1)]  # 3 ay

    fares: list[dict] = []
    runs: dict[str, dict] = {}

    for route, carriers in ROUTES.items():
        o, d = route
        otype = ond_type_of(o, d)
        dates = local_dates if otype == "Local" else beyond_dates
        mult = _long_haul_mult(route)

        for ci, cd in enumerate(dates):
            cds = cd.isoformat()
            for al in carriers:
                brands = [b for b in BRANDS[al]
                          if not (b.get("long_only") and route not in LONG_HAUL)]
                # Olay: PC "Advantage" 2026-06-18 sonrası kaldırıldı
                if al == "PC" and cds > "2026-06-18":
                    brands = [b for b in brands if b["brand"] != "Advantage"]
                # Olay: LH "Economy Green" 2026-06-25 itibarıyla eklendi
                if al == "LH" and cds >= "2026-06-25":
                    brands = brands + [{"cabin": "Economy", "brand": "Economy Green",
                                        "code": "G", "base": 305}]
                # Kabin içi sıralama için taban fiyata göre sırala
                brands = sorted(brands, key=lambda b: (b["cabin"], b["base"]))

                by_cabin: dict[str, list[dict]] = {}
                for b in brands:
                    by_cabin.setdefault(b["cabin"], []).append(b)

                for cabin, blist in by_cabin.items():
                    for tier, b in enumerate(blist):
                        usd = _drift(f"{al}{o}{d}{b['brand']}", ci, b["base"] * mult)
                        # Olay: EK anomali (2026-07-02, IST-DXB Business +%38)
                        if (al == "EK" and cds == "2026-07-02" and route == ("IST", "DXB")
                                and cabin == "Business"):
                            usd = round(usd * 1.38, 0)
                        # Olay: AF kampanyası (2026-07-16, Economy -%18)
                        if al == "AF" and cds == "2026-07-16" and cabin == "Economy":
                            usd = round(usd * 0.82, 0)

                        ccy = CARRIER_CCY[al]
                        price_local = round(usd * CCY_SCALE[ccy], 0)
                        fares.append({
                            "coll_date": cds,
                            "collection_time": f"{cds}T06:{(ci * 7) % 60:02d}:00",
                            "airline": al,
                            "airline_name": CARRIER_NAMES[al],
                            "origin": o, "destination": d,
                            "travel_date": (cd + timedelta(days=21)).isoformat(),
                            "region": region_of(o, d),
                            "ond_type": otype,
                            "season": season_of(cds),
                            "carrier_type": carrier_type_of(al),
                            "cabin": cabin,
                            "fare_brand": b["brand"],
                            "brand_code": b["code"],
                            "booking_class": b["code"][0],
                            "price": price_local, "currency": ccy,
                            "price_usd": to_usd(price_local, ccy),
                            "package_order": tier + 1,
                            "features": {f: _feature_state(f, tier, len(blist), cabin)
                                         for f in FEATURES},
                            "source": "demo",
                        })

            # Arşiv koşusu kaydı (CollDate + tip başına bir run)
            rid = f"run_{cds.replace('-', '')}_{otype.lower()}"
            r = runs.setdefault(rid, {
                "run_id": rid, "coll_date": cds,
                "collected_at": f"{cds}T06:45:00",
                "airlines": [], "onds": [], "record_count": 0, "status": "OK",
                "ond_type": otype,
            })
            r["airlines"] = sorted(set(r["airlines"]) | set(carriers))
            r["onds"] = sorted(set(r["onds"]) | {f"{o}-{d}"})

    for f in fares:
        for r in runs.values():
            if r["coll_date"] == f["coll_date"] and f"{f['origin']}-{f['destination']}" in r["onds"]:
                r["record_count"] += 1

    knowhow = {
        "TK": ["Referans taşıyıcı: tüm karşılaştırmalar TK'ya göre yapılır.",
               "EcoFly/ExtraFly/PrimeFly yapısı tüm dış hatlarda tutarlı."],
        "LH": ["ABD uçuşlarında farklı paket kuralları uygulanıyor.",
               "Avrupa içinde Light tarifesi bulunuyor.",
               "Premium Economy sadece uzun menzilli hatlarda mevcut.",
               "Yaz sezonunda kampanya uygulanıyor."],
        "AF": ["Economy Light uzun menzilde bagajsız satılıyor.",
               "Premium kabin yalnızca seçili hatlarda."],
        "EK": ["Special tarifesi iade edilemez, değişiklik ücretli.",
               "Flex Plus mil kazanımı %200'e çıkıyor."],
        "SQ": ["Economy Lite'ta koltuk seçimi ücretli.",
               "Premium Economy yalnızca geniş gövde uçuşlarda."],
        "PC": ["Low cost model: tüm ekstralar ücretli.",
               "Basic pakette yalnızca kabin bagajı dahil."],
    }

    return {
        "generated_at": f"{TODAY.isoformat()}T07:00:00",
        "count": len(fares),
        "fares": fares,
        "runs": sorted(runs.values(), key=lambda r: (r["coll_date"], r["run_id"])),
        "knowhow": knowhow,
    }


def main() -> None:
    data = build()
    out = ROOT / "output" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"data.json yazıldı: {out} ({data['count']} kayıt, "
          f"{len(data['runs'])} run)")

    if "--embed" in sys.argv:
        html_path = ROOT / "web" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        marker_a = "/*__EMBEDDED_DATA_START__*/"
        marker_b = "/*__EMBEDDED_DATA_END__*/"
        a, b = html.index(marker_a) + len(marker_a), html.index(marker_b)
        html = html[:a] + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + html[b:]
        html_path.write_text(html, encoding="utf-8")
        print(f"Gömüldü: {html_path}")


if __name__ == "__main__":
    main()
