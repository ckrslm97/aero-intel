"""OND (Origin-Destination) modeli ve liste yükleyici.

Kullanıcı "OND Listesini Yükle" ile CSV veya Excel dosyası seçtiğinde
dosya bu modülde ayrıştırılır. Beklenen format:

    AIRLINE | ORIGIN | DESTINATION

Örn:  TK | IST | LHR
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


# Dosyada aranacak sütun adları (büyük/küçük harf duyarsız eşleştirilir).
_AIRLINE_COLS = {"airline", "airlines", "carrier", "carriers",
                 "havayolu", "havayollari", "havayolları", "taşıyıcı",
                 "taşıyıcılar", "tasiyici", "tasiyicilar"}
_ORIGIN_COLS = {"origin", "orig", "from", "kalkis", "kalkış"}
_DEST_COLS = {"destination", "dest", "to", "varis", "varış"}

# Bir sayfanın "taşıyıcı listesi" sayfası olduğunu düşündüren ad ipuçları.
_CARRIER_SHEET_HINTS = {"carrier", "carriers", "airline", "airlines",
                        "havayolu", "taşıyıcı", "tasiyici"}


def _split_carriers(raw: str) -> list[str]:
    """'AF,JL/NH' gibi çok taşıyıcılı metni tekil kodlara ayırır."""
    raw = str(raw).replace("/", ",").replace(";", ",").replace("|", ",")
    out: list[str] = []
    for a in raw.split(","):
        code = a.strip().upper()
        if code and code != "NAN":
            out.append(code)
    return out


@dataclass(frozen=True)
class OND:
    """Tek bir taşıyıcı + rota kombinasyonu.

    Not: Prompttaki örnekte bir rota için birden çok taşıyıcı virgülle
    verilebiliyor (örn. "AF,JL,NH"). Yükleyici bunu her taşıyıcı için
    ayrı bir OND'ye açar.
    """

    airline: str
    origin: str
    destination: str

    @property
    def key(self) -> str:
        """Resume/dedup için benzersiz anahtar."""
        return f"{self.airline}_{self.origin}_{self.destination}".upper()

    def __str__(self) -> str:
        return f"{self.airline} {self.origin}-{self.destination}"


def _match_column(columns: list[str], candidates: set[str]) -> str | None:
    """Sütun adlarını aday kümesiyle eşleştirir; ilk eşleşeni döndürür."""
    for col in columns:
        if col.strip().lower() in candidates:
            return col
    return None


def load_ond_file(path: str | Path) -> list[OND]:
    """CSV veya Excel dosyasından OND (rota) + taşıyıcı listesini yükler.

    Desteklenen biçimler:
    - **Tek tablo:** ``AIRLINE | ORIGIN | DESTINATION`` (çok taşıyıcılı hücre
      ``AF,JL,NH`` desteklenir).
    - **Rota + taşıyıcı ayrı:** Rota satırlarında taşıyıcı boşsa, ayrı bir
      taşıyıcı listesi (Excel'de "Carriers" adlı sayfa ya da yalnızca taşıyıcı
      sütunu olan bir sayfa/sütun) rotalarla **çaprazlanır** — her rota × her
      taşıyıcı için ayrı OND üretilir.
    - **Çok sayfalı Excel:** origin/dest içeren tüm sayfalar rota olarak okunur.

    Args:
        path: ``.csv``, ``.xlsx`` veya ``.xls`` dosya yolu.

    Returns:
        Ayrıştırılmış ve tekilleştirilmiş OND listesi.

    Raises:
        ValueError: Rota (ORIGIN/DESTINATION) bulunamazsa.
        FileNotFoundError: Dosya yoksa.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"OND dosyası bulunamadı: {path}")

    # {sayfa_adı: DataFrame} — CSV tek sayfa gibi ele alınır.
    if path.suffix.lower() in {".xlsx", ".xls"}:
        sheets: dict[str, pd.DataFrame] = pd.read_excel(path, dtype=str, sheet_name=None)
    else:
        sheets = {"data": pd.read_csv(path, dtype=str, sep=None, engine="python")}

    for name, df in sheets.items():
        df.columns = [str(c) for c in df.columns]

    global_carriers = _collect_global_carriers(sheets)

    onds: list[OND] = []
    seen: set[str] = set()
    found_routes = False

    for name, df in sheets.items():
        cols = list(df.columns)
        origin_col = _match_column(cols, _ORIGIN_COLS)
        dest_col = _match_column(cols, _DEST_COLS)
        if not (origin_col and dest_col):
            continue  # rota sayfası değil (örn. yalnızca taşıyıcı listesi)
        found_routes = True
        airline_col = _match_column(cols, _AIRLINE_COLS)

        for _, r in df.iterrows():
            origin = str(r[origin_col]).strip().upper()
            dest = str(r[dest_col]).strip().upper()
            if not origin or not dest or origin == "NAN" or dest == "NAN":
                continue
            row_carriers = _split_carriers(r[airline_col]) if airline_col else []
            carriers = row_carriers or global_carriers
            if not carriers:
                continue  # taşıyıcı yok: bu rota atlanır
            for airline in carriers:
                ond = OND(airline=airline, origin=origin, destination=dest)
                if ond.key not in seen:
                    seen.add(ond.key)
                    onds.append(ond)

    if not found_routes:
        raise ValueError(
            "Dosyada ORIGIN / DESTINATION sütunları bulunamadı. "
            f"Bulunan sayfalar/sütunlar: "
            f"{ {n: list(d.columns) for n, d in sheets.items()} }"
        )
    return onds


def _collect_global_carriers(sheets: dict[str, "pd.DataFrame"]) -> list[str]:
    """Rota satırında taşıyıcı olmadığında kullanılacak genel taşıyıcı listesi.

    Kaynak: adı taşıyıcıyı çağrıştıran bir sayfa, ya da origin/dest içermeyip
    yalnızca taşıyıcı sütunu bulunan bir sayfa. Bulunanlar birleştirilir.
    """
    carriers: list[str] = []
    seen: set[str] = set()

    def _add(values: object) -> None:
        for code in _split_carriers(str(values)):
            if code not in seen:
                seen.add(code)
                carriers.append(code)

    for name, df in sheets.items():
        cols = list(df.columns)
        has_route = _match_column(cols, _ORIGIN_COLS) and _match_column(cols, _DEST_COLS)
        carrier_col = _match_column(cols, _AIRLINE_COLS)
        name_is_carrier_sheet = any(h in name.strip().lower() for h in _CARRIER_SHEET_HINTS)

        if has_route:
            # Rota sayfası: yalnızca satır-içi taşıyıcı kullanılır, genel listeye katma.
            continue
        if carrier_col:
            for v in df[carrier_col].tolist():
                _add(v)
        elif name_is_carrier_sheet:
            # Başlıksız/serbest taşıyıcı sayfası: tüm hücreleri tara.
            for v in df.to_numpy().ravel().tolist():
                _add(v)
    return carriers


def ond_from_fields(airline: str, origin: str, destination: str) -> list[OND]:
    """Tek bir GUI satırından (airline, origin, destination) OND listesi üretir.

    ``airline`` çoklu olabilir (``TK,AF`` / ``TK/AF``) → her taşıyıcı için ayrı
    OND. Eksik/boş alanlarda ``ValueError`` fırlatır (GUI kullanıcıya gösterir).
    """
    origin = str(origin).strip().upper()
    destination = str(destination).strip().upper()
    carriers = _split_carriers(airline)
    if not carriers:
        raise ValueError("En az bir taşıyıcı girin (örn. TK veya TK,AF).")
    if not origin or not destination:
        raise ValueError("Origin ve Destination zorunludur.")
    out: list[OND] = []
    seen: set[str] = set()
    for a in carriers:
        ond = OND(airline=a, origin=origin, destination=destination)
        if ond.key not in seen:
            seen.add(ond.key)
            out.append(ond)
    return out


def parse_inline_routes(spec: str) -> list[OND]:
    """Satır içi rota tanımını OND listesine çevirir (CLI kolaylığı).

    Biçim: ``"AIRLINE:ORIG-DEST"`` öğeleri virgülle ayrılır; taşıyıcı çoklu
    olabilir (``TK/AF:IST-LHR``). Örn:
        ``"TK:IST-LHR, AF:CDG-JFK, TK/AF:IST-CDG"``

    Raises:
        ValueError: Bir öğe ``AIRLINE:ORIG-DEST`` biçimine uymazsa.
    """
    onds: list[OND] = []
    seen: set[str] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"Geçersiz rota (AIRLINE:ORIG-DEST bekleniyordu): {part!r}")
        carriers_s, route = part.split(":", 1)
        route = route.replace("→", "-").replace("–", "-").strip()
        if "-" not in route:
            raise ValueError(f"Geçersiz rota (ORIG-DEST bekleniyordu): {part!r}")
        origin, dest = (x.strip().upper() for x in route.split("-", 1))
        if not origin or not dest:
            raise ValueError(f"Eksik origin/destination: {part!r}")
        for airline in _split_carriers(carriers_s):
            ond = OND(airline=airline, origin=origin, destination=dest)
            if ond.key not in seen:
                seen.add(ond.key)
                onds.append(ond)
    return onds
