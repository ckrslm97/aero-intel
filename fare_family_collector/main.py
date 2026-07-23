"""Uygulama giriş noktası.

Kullanım:
    python main.py                          # Arayüzü (GUI) başlatır
    python main.py --cli FILE               # Arayüzsüz, verilen OND dosyasını işler
    python main.py --cli FILE --demo-mode   # Canlı istek atmadan sahte veri
    python main.py --routes "TK:IST-LHR,AF:CDG-JFK"   # Dosyasız satır içi rota
    python main.py --demo                   # Örnek OND listesiyle demo (tam çevrimdışı)

CLI modu, sunucuda/başsız ortamda (örneğin paylaşımlı HTML panelini
besleyen bir cron işi olarak) çalıştırmak için uygundur.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import CONFIG
from core.exporter import Exporter
from core.logging_config import setup_logging
from core.ond import OND, load_ond_file, parse_inline_routes
from core.runner import CollectorRunner


def run_onds(onds: list[OND], only_due: bool = False) -> int:
    """Verilen OND listesini işler ve çıktıları yazar.

    Args:
        onds: İşlenecek OND listesi (dosya ve/veya satır içi kaynaklardan).
        only_due: True ise frekans planına göre yalnızca zamanı gelen
            OND'ler çekilir (Local: haftalık, Beyond: aylık).
    """
    log = setup_logging(CONFIG.log_dir)
    mode = "DEMO (çevrimdışı)" if CONFIG.demo_mode else "CANLI"
    log.info("%d OND işlenecek — mod: %s", len(onds), mode)

    def _progress(done: int, total: int) -> None:
        pct = (done / total * 100) if total else 0
        print(f"\rİlerleme: {done}/{total} ({pct:.0f}%)", end="", flush=True)

    runner = CollectorRunner(CONFIG, on_progress=_progress)
    fares, summary = runner.run(onds, CONFIG.default_travel_date or None, only_due=only_due)
    print()
    written = Exporter(CONFIG).export_all(fares)
    log.info("Özet:\n%s", summary.as_text())
    for fmt, path in written.items():
        log.info("%s → %s", fmt.upper(), path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Havayolu Fare Family Veri Toplama")
    parser.add_argument("--cli", metavar="OND_FILE", help="Arayüzsüz çalış (CSV/Excel OND dosyası)")
    parser.add_argument("--routes", metavar="SPEC",
                        help="Satır içi rota: 'TK:IST-LHR,AF:CDG-JFK' (dosyayla birleşebilir)")
    parser.add_argument("--demo", action="store_true", help="Örnek OND listesiyle demo çalışması")
    parser.add_argument("--demo-mode", dest="demo_mode", action="store_true",
                        help="--cli/--routes ile: canlı istek atmadan sahte veri üret (Playwright gerekmez)")
    parser.add_argument("--no-ota", dest="no_ota", action="store_true",
                        help="Havayolu sitesi başarısız olsa bile OTA yedeğine düşme")
    parser.add_argument("--due", action="store_true", help="Frekans planına göre yalnızca zamanı gelen OND'leri çek (Local: haftalık, Beyond: aylık)")
    args = parser.parse_args()

    if args.no_ota:
        CONFIG.use_ota_fallback = False

    if args.demo:
        # Demo modu: canlı istek atılmaz, tüm havayolları için sahte veri
        # üretilir; Playwright kurulu olmasa da uçtan uca hatasız çalışır.
        CONFIG.demo_mode = True
        onds = load_ond_file(str(Path(__file__).parent / "data" / "ond_example.csv"))
        return run_onds(onds, only_due=args.due)

    if args.cli or args.routes:
        CONFIG.demo_mode = args.demo_mode
        onds: list[OND] = []
        seen: set[str] = set()
        if args.cli:
            onds.extend(load_ond_file(args.cli))
        if args.routes:
            onds.extend(parse_inline_routes(args.routes))
        # Dosya + satır içi birleşiminde tekilleştir.
        deduped = [o for o in onds if not (o.key in seen or seen.add(o.key))]
        if not deduped:
            print("İşlenecek OND bulunamadı.", file=sys.stderr)
            return 1
        return run_onds(deduped, only_due=args.due)

    # Varsayılan: GUI
    try:
        from gui.app import launch
    except ImportError as exc:
        print(f"GUI başlatılamadı ({exc}). 'pip install customtkinter' gerekli.", file=sys.stderr)
        print("Arayüzsüz çalışmak için: python main.py --demo", file=sys.stderr)
        return 1
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
