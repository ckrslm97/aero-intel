"""Çalışma orkestrasyonu.

`CollectorRunner`, OND listesini `ThreadPoolExecutor` ile paralel işler,
ilerleme/log geri çağrılarını (callback) tetikler, resume (kaldığı yerden
devam) ve dedup (aynı OND'yi tekrar çekmeme) destekler.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from config import AppConfig
from core.logging_config import get_logger
from core.models import FareBrand, RunSummary
from core.ond import OND
from scrapers.base import ScrapeError
from scrapers.registry import get_scraper, has_real_scraper, load_all_scrapers

log = get_logger("runner")

# Callback tipleri
ProgressCallback = Callable[[int, int], None]      # (tamamlanan, toplam)
LogCallback = Callable[[str], None]                # (mesaj)
ResultCallback = Callable[[OND, list[FareBrand]], None]


class CollectorRunner:
    """OND listesini paralel işleyen ana yürütücü."""

    def __init__(
        self,
        config: AppConfig,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
        on_result: ResultCallback | None = None,
    ) -> None:
        self.config = config
        self.on_progress = on_progress
        self.on_log = on_log
        self.on_result = on_result
        self._stop_event = threading.Event()
        self._resume_path = config.output_dir / "_resume.json"
        load_all_scrapers()  # registry'yi doldur

    # ------------------------------------------------------------------ #
    # Kontrol
    # ------------------------------------------------------------------ #
    def stop(self) -> None:
        """Çalışmayı nazikçe durdurur (yeni OND başlatılmaz)."""
        self._stop_event.set()

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.on_log:
            self.on_log(msg)

    # ------------------------------------------------------------------ #
    # Resume durumu
    # ------------------------------------------------------------------ #
    def _load_done(self) -> set[str]:
        """Daha önce tamamlanmış OND anahtarlarını yükler."""
        if self.config.resume and self._resume_path.exists():
            try:
                return set(json.loads(self._resume_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                return set()
        return set()

    def _save_done(self, done: set[str]) -> None:
        try:
            self._resume_path.write_text(json.dumps(sorted(done)), encoding="utf-8")
        except OSError as exc:
            log.warning("Resume durumu yazılamadı: %s", exc)

    def reset_resume(self) -> None:
        """Resume durumunu temizler (baştan çekmek için)."""
        self._resume_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Ana çalışma
    # ------------------------------------------------------------------ #
    def run(self, onds: list[OND], travel_date: str | None = None,
            only_due: bool = False) -> tuple[list[FareBrand], RunSummary]:
        """Tüm OND listesini işler.

        Args:
            onds: İşlenecek OND listesi.
            travel_date: Ortak uçuş tarihi (None ise config'ten çözülür).
            only_due: True ise frekans planına göre yalnızca zamanı gelen
                OND'ler çekilir (Local: haftalık, Beyond: aylık).

        Returns:
            (tüm_fareler, özet_rapor) ikilisi.
        """
        from core.enrich import check_quality, enrich_all
        from core.exporter import Exporter
        from core.scheduler import due_onds

        self._stop_event.clear()
        start = time.time()

        if only_due:
            index = Exporter(self.config).load_archive_index()
            before = len(onds)
            onds = due_onds(onds, index)
            self._log(
                f"Frekans planı (Local=haftalık, Beyond=aylık): "
                f"{len(onds)}/{before} OND zamanı geldiği için çekilecek."
            )

        done = self._load_done() if self.config.skip_existing else set()

        pending = [o for o in onds if o.key not in done]
        skipped = len(onds) - len(pending)
        if skipped:
            self._log(f"{skipped} OND daha önce çekilmiş, atlanıyor (resume).")

        summary = RunSummary(total_ond=len(onds), success=skipped)
        all_fares: list[FareBrand] = []
        results_lock = threading.Lock()
        completed = skipped

        def _emit_progress() -> None:
            if self.on_progress:
                self.on_progress(completed, len(onds))

        def _record(ond: OND, outcome: "list[FareBrand] | Exception") -> None:
            """Tek bir OND sonucunu (fare listesi ya da hata) kaydeder.

            Özet, resume ve geri çağrıları thread-güvenli biçimde günceller.
            """
            nonlocal completed
            with results_lock:
                if isinstance(outcome, list):
                    all_fares.extend(outcome)
                    summary.success += 1
                    summary.total_fares += len(outcome)
                    done.add(ond.key)
                    ok = True
                else:
                    summary.failed += 1
                    ok = False
                completed += 1
            if ok:
                self._log(f"{ond}: {len(outcome)} paket kaydedildi ✔")
                if self.on_result:
                    self.on_result(ond, outcome)
            else:
                self._log(f"{ond}: HATA — {outcome}")
            _emit_progress()
            self._save_done(done)

        _emit_progress()

        if self.config.demo_mode:
            # Demo/çevrimdışı: OND başına DemoScraper (sync, thread havuzu).
            self._run_pool(pending, travel_date, _record)
        else:
            # Canlı: taşıyıcıya göre grupla, her grup tek tarayıcıda çok sekmeyle
            # (async) çekilir; boş/başarısız OND'ler OTA yedeğine düşer.
            self._run_live(pending, travel_date, _record)

        summary.duration_seconds = time.time() - start

        # Zenginleştirme: CollDate, sezon, Local/Beyond, region, USD dönüşümü
        all_fares = enrich_all(all_fares)

        # Veri kalitesi kontrolleri (eksik / tutarsız / duplicate / kur hatası)
        issues = check_quality(all_fares)
        if issues:
            self._log(f"⚠ Veri kalitesi: {len(issues)} uyarı bulundu "
                      f"(ayrıntılar log dosyasında).")
            for msg in issues[:10]:
                self._log(f"  • {msg}")

        self._log("Çalışma tamamlandı.\n" + summary.as_text())
        return all_fares, summary

    # ------------------------------------------------------------------ #
    # Yürütme stratejileri
    # ------------------------------------------------------------------ #
    def _resolve_travel_date(self, travel_date: str | None) -> str:
        """Ortak uçuş tarihini çözer (async motor somut bir tarih ister)."""
        if travel_date:
            return travel_date
        if self.config.default_travel_date:
            return self.config.default_travel_date
        return (date.today() + timedelta(days=self.config.default_days_ahead)).isoformat()

    def _run_pool(
        self, pending: list[OND], travel_date: str | None,
        record: "Callable[[OND, list[FareBrand] | Exception], None]",
    ) -> None:
        """OND başına `_process_one` (sync) — demo modu için thread havuzu."""
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            future_to_ond = {
                pool.submit(self._process_one, ond, travel_date): ond for ond in pending
            }
            for future in as_completed(future_to_ond):
                if self._stop_event.is_set():
                    self._log("Durdurma istendi; kalan işler iptal ediliyor.")
                    for f in future_to_ond:
                        f.cancel()
                    break
                ond = future_to_ond[future]
                try:
                    record(ond, future.result())
                except Exception as exc:  # noqa: BLE001
                    record(ond, exc)

    def _run_live(
        self, pending: list[OND], travel_date: str | None,
        record: "Callable[[OND, list[FareBrand] | Exception], None]",
    ) -> None:
        """Canlı toplama: taşıyıcıya göre grupla, her grubu async çok-sekme motoruyla çek.

        Taşıyıcı grupları bir thread havuzunda **paralel** işlenir (her thread kendi
        olay döngüsü + tarayıcısı); her grup **içinde** ise `pages_per_browser` kadar
        sekme **eşzamanlı** sorgu atar ve çerez tek sefer kabul edilir.
        """
        resolved = self._resolve_travel_date(travel_date)
        groups: dict[str, list[OND]] = defaultdict(list)
        for ond in pending:
            groups[ond.airline.upper()].append(ond)

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            future_to_airline = {
                pool.submit(self._run_carrier_group, airline, group, resolved): airline
                for airline, group in groups.items()
            }
            for future in as_completed(future_to_airline):
                if self._stop_event.is_set():
                    self._log("Durdurma istendi; kalan işler iptal ediliyor.")
                    for f in future_to_airline:
                        f.cancel()
                    break
                for ond, outcome in future.result():
                    record(ond, outcome)

    def _run_carrier_group(
        self, airline: str, group: list[OND], travel_date: str,
    ) -> list[tuple[OND, "list[FareBrand] | Exception"]]:
        """Bir taşıyıcının OND grubunu async motorla çeker; boşları OTA'ya düşürür.

        Thread içinde çalışır ve her OND için ``(ond, fareler|hata)`` döndürür;
        sonuç kaydı (özet/callback) çağıran ana döngüde `record` ile yapılır.
        """
        from core.async_engine import scrape_group

        self._log(f"{airline}: {len(group)} rota tek tarayıcıda eşzamanlı çekiliyor…")
        has_real = has_real_scraper(airline)
        engine_results: dict[str, list[FareBrand] | Exception] = {}
        if has_real:
            try:
                scraper = get_scraper(airline, self.config)
                engine_results = asyncio.run(scrape_group(scraper, group, travel_date, self.config))
            except Exception as exc:  # noqa: BLE001 - motor tümüyle patlarsa (ör. Playwright yok)
                engine_results = {o.key: exc for o in group}

        outcomes: list[tuple[OND, list[FareBrand] | Exception]] = []
        for ond in group:
            res = engine_results.get(ond.key)
            if isinstance(res, list) and res:
                outcomes.append((ond, res))
                continue

            errors: list[str] = []
            if isinstance(res, Exception):
                errors.append(f"havayolu sitesi: {res}")
            elif has_real:
                errors.append("havayolu sitesi: boş sonuç")
            else:
                errors.append(f"{airline} için kayıtlı site scraper'ı yok")

            if self.config.use_ota_fallback:
                self._log(f"{ond}: havayolu sitesinden veri alınamadı; OTA yedeği deneniyor…")
                try:
                    ota_fares = self._try_ota(ond, travel_date, errors)
                except Exception as exc:  # noqa: BLE001
                    ota_fares = []
                    errors.append(str(exc))
                if ota_fares:
                    outcomes.append((ond, ota_fares))
                    continue

            outcomes.append((
                ond,
                ScrapeError(f"{ond}: veri alınamadı ({'; '.join(errors) or 'kaynak yok'})"),
            ))
        return outcomes

    def _process_one(self, ond: OND, travel_date: str | None) -> list[FareBrand]:
        """Tek bir OND'yi işler; gerekirse OTA yedeğine düşer (thread içinde).

        Akış:
        - Demo modda: doğrudan DemoScraper (canlı istek yok, her zaman başarılı).
        - Canlı modda: havayolunun kendi scraper'ı denenir; başarısız/boşsa
          `config.ota_sources` sırasıyla OTA kaynakları denenir. Havayolunun
          kayıtlı gerçek scraper'ı yoksa (site akışı bilinmiyorsa) doğrudan
          OTA'ya geçilir. Hiçbiri veri veremezse OND başarısız sayılır.
        """
        self._log(f"{ond} başladı")

        # Demo / çevrimdışı: her zaman DemoScraper.
        if self.config.demo_mode:
            return get_scraper(ond.airline, self.config).run(ond, travel_date)

        errors: list[str] = []

        # 1) Havayolunun kendi sitesi (yalnızca gerçek scraper varsa).
        if has_real_scraper(ond.airline):
            try:
                fares = get_scraper(ond.airline, self.config).run(ond, travel_date)
                if fares:
                    return fares
                errors.append("havayolu sitesi: boş sonuç")
            except Exception as exc:  # noqa: BLE001 - OTA'ya düşmek için geniş yakalama
                errors.append(f"havayolu sitesi: {exc}")
            self._log(f"{ond}: havayolu sitesinden veri alınamadı; OTA yedeği deneniyor…")
        else:
            self._log(f"{ond}: {ond.airline} için kayıtlı site scraper'ı yok; OTA deneniyor…")

        # 2) OTA yedek zinciri.
        if self.config.use_ota_fallback:
            ota_fares = self._try_ota(ond, travel_date, errors)
            if ota_fares:
                return ota_fares

        raise ScrapeError(f"{ond}: veri alınamadı ({'; '.join(errors) or 'kaynak yok'})")

    def _try_ota(self, ond: OND, travel_date: str | None, errors: list[str]) -> list[FareBrand]:
        """OTA kaynaklarını sırayla dener; ilk veri döneni kullanır."""
        from scrapers.ota_base import get_ota_scraper

        for name in self.config.ota_sources:
            scraper = get_ota_scraper(name, self.config, ond.airline)
            if scraper is None:
                errors.append(f"ota:{name} kayıtlı değil")
                continue
            try:
                fares = scraper.run(ond, travel_date)
                if fares:
                    self._log(f"{ond}: OTA '{name}' üzerinden {len(fares)} paket ✔")
                    return fares
                errors.append(f"ota:{name}: boş sonuç")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ota:{name}: {exc}")
        return []
