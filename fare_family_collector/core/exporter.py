"""Çıktı (export) katmanı.

Toplanan `FareBrand` kayıtlarını Excel, CSV, SQLite ve JSON biçimlerinde
yazar. JSON çıktısı ayrıca HTML paneli (`web/index.html`) tarafından
okunacak `data.json` dosyasını da üretir.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import AppConfig
from core.logging_config import get_logger
from core.models import FareBrand

log = get_logger("exporter")


class Exporter:
    """Fare kayıtlarını çeşitli biçimlere yazan sınıf."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def to_dataframe(self, fares: list[FareBrand]) -> pd.DataFrame:
        """Fare listesini düz bir DataFrame'e çevirir."""
        return pd.DataFrame([f.to_row() for f in fares])

    def export_all(self, fares: list[FareBrand]) -> dict[str, Path]:
        """Yapılandırmaya göre etkin tüm biçimlere yazar.

        Returns:
            {biçim: yazılan_dosya_yolu} sözlüğü.
        """
        written: dict[str, Path] = {}
        if not fares:
            log.warning("Yazılacak fare yok.")
            return written

        df = self.to_dataframe(fares)
        stamp = self._timestamp()

        if self.config.export_excel:
            written["excel"] = self._to_excel(df, stamp)
        if self.config.export_csv:
            written["csv"] = self._to_csv(df, stamp)
        written["tsv"] = self.to_tsv(fares, stamp)  # Ham veri her zaman TSV olarak da saklanır
        if self.config.export_sqlite:
            written["sqlite"] = self._to_sqlite(df)
        if self.config.export_json:
            written["json"] = self._to_json(fares, stamp)
        written["archive"] = self.archive_run(fares, df, stamp)

        return written

    # ------------------------------------------------------------------ #
    # TSV (ham veri) export
    # ------------------------------------------------------------------ #
    def to_tsv(self, fares: list[FareBrand], stamp: str | None = None,
               path: Path | None = None) -> Path:
        """Ham veriyi TSV olarak yazar (tek tıkla export'un arka ucu).

        GUI'deki "TSV Export" düğmesi ve Archive indirme bağlantıları bu
        metodu kullanır. ``path`` verilirse oraya, verilmezse
        ``output/fares_<stamp>.tsv`` dosyasına yazar.
        """
        stamp = stamp or self._timestamp()
        path = path or (self.output_dir / f"fares_{stamp}.tsv")
        df = self.to_dataframe(fares)
        df.to_csv(path, index=False, sep="\t", encoding="utf-8-sig")
        log.info("TSV yazıldı: %s", path)
        return path

    # ------------------------------------------------------------------ #
    # Archive: her çekim kalıcı olarak saklanır
    # ------------------------------------------------------------------ #
    def archive_run(self, fares: list[FareBrand], df: pd.DataFrame, stamp: str) -> Path:
        """Çekimi ``output/archive/run_<stamp>/`` altında kalıcı arşivler.

        Klasör içeriği: raw.tsv, fares.xlsx, fares.json, fares.db.
        ``archive/index.json`` dosyasına da bir özet kaydı eklenir; hem
        masaüstü Archive sekmesi hem HTML paneli bu indeksi okur.
        """
        arch_root = self.output_dir / "archive"
        run_dir = arch_root / f"run_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        df.to_csv(run_dir / "raw.tsv", index=False, sep="\t", encoding="utf-8-sig")
        with pd.ExcelWriter(run_dir / "fares.xlsx", engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Fares")
        with sqlite3.connect(run_dir / "fares.db") as conn:
            df.to_sql("fares", conn, if_exists="replace", index=False)
        (run_dir / "fares.json").write_text(
            json.dumps([f.to_json() for f in fares], ensure_ascii=False),
            encoding="utf-8",
        )

        entry = {
            "run_id": f"run_{stamp}",
            "coll_date": getattr(fares[0], "coll_date", "") if fares else "",
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "airlines": sorted({f.airline for f in fares}),
            "onds": sorted({f"{f.origin}-{f.destination}" for f in fares}),
            "record_count": len(fares),
            "status": "OK" if fares else "EMPTY",
        }
        index_path = arch_root / "index.json"
        index: list[dict] = []
        if index_path.exists():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                index = []
        index.append(entry)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Arşivlendi: %s (%d kayıt)", run_dir, len(fares))
        return run_dir

    def load_archive_index(self) -> list[dict]:
        """Archive indeksini okur (GUI Archive sekmesi için)."""
        index_path = self.output_dir / "archive" / "index.json"
        if not index_path.exists():
            return []
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _to_excel(self, df: pd.DataFrame, stamp: str) -> Path:
        path = self.output_dir / f"fares_{stamp}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Fares")
            self._autosize(writer.sheets["Fares"], df)
        log.info("Excel yazıldı: %s", path)
        return path

    @staticmethod
    def _autosize(worksheet, df: pd.DataFrame) -> None:
        """Sütun genişliklerini içeriğe göre ayarlar (okunabilirlik)."""
        for i, col in enumerate(df.columns, start=1):
            max_len = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)])
            worksheet.column_dimensions[_col_letter(i)].width = min(max_len + 2, 48)

    def _to_csv(self, df: pd.DataFrame, stamp: str) -> Path:
        path = self.output_dir / f"fares_{stamp}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        log.info("CSV yazıldı: %s", path)
        return path

    def _to_sqlite(self, df: pd.DataFrame) -> Path:
        path = self.output_dir / "fares.db"
        with sqlite3.connect(path) as conn:
            df.to_sql("fares", conn, if_exists="append", index=False)
        log.info("SQLite yazıldı: %s", path)
        return path

    def _to_json(self, fares: list[FareBrand], stamp: str) -> Path:
        """Zaman damgalı JSON + panel için KÜMÜLATİF data.json üretir.

        data.json geçmiş CollDate'lerin verisini korur; böylece HTML paneli
        zaman serisi analizleri (Line Chart, Paket Evrimi, uyarılar)
        yapabilir. Aynı (CollDate, havayolu, OND, kabin, marka) anahtarı
        gelirse yeni kayıt eskisini ezer.
        """
        new_rows = [f.to_json() for f in fares]
        stamped = self.output_dir / f"fares_{stamp}.json"
        stamped.write_text(
            json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                        "count": len(new_rows), "fares": new_rows},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # --- Kümülatif panel verisi ---
        latest = self.output_dir / "data.json"
        history: list[dict] = []
        if latest.exists():
            try:
                history = json.loads(latest.read_text(encoding="utf-8")).get("fares", [])
            except (json.JSONDecodeError, OSError):
                history = []

        def _key(r: dict) -> tuple:
            return (r.get("coll_date"), r.get("airline"), r.get("origin"),
                    r.get("destination"), r.get("cabin"), r.get("fare_brand"))

        merged: dict[tuple, dict] = {_key(r): r for r in history}
        for r in new_rows:
            merged[_key(r)] = r

        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(merged),
            "fares": list(merged.values()),
            "runs": self.load_archive_index(),
        }
        latest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        log.info("JSON yazıldı: %s (+ kümülatif data.json, %d kayıt)", stamped, len(merged))
        return stamped


def _col_letter(idx: int) -> str:
    """1 tabanlı sütun indeksini Excel harfine çevirir (1->A, 27->AA)."""
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
