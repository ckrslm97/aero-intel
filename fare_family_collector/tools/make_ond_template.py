"""OND + taşıyıcı Excel şablonu üretici.

`data/ond_template.xlsx` dosyasını iki sayfayla üretir:

- **Routes**   : ORIGIN | DESTINATION (ve opsiyonel AIRLINE) — rota listesi.
- **Carriers** : CARRIER — taşıyıcı listesi. Routes sayfasında taşıyıcı boşsa
                 bu liste her rota ile çaprazlanır (rota × taşıyıcı).

Ayrıca tek sayfalık klasik biçim (AIRLINE | ORIGIN | DESTINATION) da
`data/ond_template_single.xlsx` olarak üretilir.

Kullanım:
    python tools/make_ond_template.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build() -> None:
    out_dir = ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # İki sayfalı: Routes (taşıyıcısız) + Carriers (çaprazlanır)
    routes = pd.DataFrame(
        {"ORIGIN": ["IST", "IST", "CDG", "FCO"],
         "DESTINATION": ["LHR", "JFK", "HND", "GRU"]}
    )
    carriers = pd.DataFrame({"CARRIER": ["TK", "AF", "LH"]})
    two_sheet = out_dir / "ond_template.xlsx"
    with pd.ExcelWriter(two_sheet, engine="openpyxl") as writer:
        routes.to_excel(writer, index=False, sheet_name="Routes")
        carriers.to_excel(writer, index=False, sheet_name="Carriers")
    print(f"Yazıldı: {two_sheet} (Routes × Carriers çaprazlama)")

    # Tek sayfalı klasik biçim (satır başına taşıyıcı; çoklu taşıyıcı virgülle)
    single = pd.DataFrame(
        {"AIRLINE": ["TK", "AF", "TK,AF,LH"],
         "ORIGIN": ["IST", "CDG", "IST"],
         "DESTINATION": ["LHR", "JFK", "CDG"]}
    )
    single_path = out_dir / "ond_template_single.xlsx"
    with pd.ExcelWriter(single_path, engine="openpyxl") as writer:
        single.to_excel(writer, index=False, sheet_name="OND")
    print(f"Yazıldı: {single_path} (tek tablo: AIRLINE|ORIGIN|DESTINATION)")


if __name__ == "__main__":
    build()
