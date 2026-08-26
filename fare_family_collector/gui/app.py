"""CustomTkinter masaüstü arayüzü.

Koyu temalı, kompakt bir kontrol paneli:
- Sol: kontroller (OND yükle, havayolu filtresi, tarih, mod, thread, export)
- Orta: fare tablosu (carrier / OND / paketler yan yana)
- Sağ: canlı log ekranı
- Alt: ilerleme çubuğu ve özet

Ağır işler (scraping) ayrı bir thread'de çalışır; arayüz donmaz.
"""
from __future__ import annotations

import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import Listbox, filedialog, ttk
from typing import Optional

import customtkinter as ctk

from config import CONFIG
from core.logging_config import setup_logging
from core.models import FareBrand, RunSummary
from core.ond import OND, load_ond_file, ond_from_fields
from core.runner import CollectorRunner
from gui import theme

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class FareCollectorApp(ctk.CTk):
    """Ana uygulama penceresi."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Fare Family Collector — Havayolu Ücret Paketi Toplama")
        self.geometry("1360x820")
        self.configure(fg_color=theme.BG_DEEP)
        self.minsize(1120, 680)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        setup_logging(CONFIG.log_dir, log_queue=self.log_queue)

        self.onds: list[OND] = []
        self.fares: list[FareBrand] = []
        self.runner: Optional[CollectorRunner] = None
        self._worker: Optional[threading.Thread] = None
        self._httpd = None            # canlı panel HTTP sunucusu
        self._panel_port: Optional[int] = None

        self._build_layout()
        self._poll_log_queue()

    # ------------------------------------------------------------------ #
    # Yerleşim
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_center()
        self._build_log_panel()
        self._build_bottom_bar()

    def _build_sidebar(self) -> None:
        bar = ctk.CTkScrollableFrame(self, width=280, fg_color=theme.BG_PANEL, corner_radius=0)
        bar.grid(row=0, column=0, sticky="nsw", rowspan=2)

        ctk.CTkLabel(bar, text="✈  KONTROL PANELİ", font=(theme.FONT_FAMILY, 16, "bold"),
                     text_color=theme.PRIMARY).pack(anchor="w", pady=(14, 10), padx=12)

        ctk.CTkButton(bar, text="📁  OND Listesini Yükle", command=self._load_ond,
                      fg_color=theme.PRIMARY, hover_color=theme.PRIMARY_HOVER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=6)
        self.ond_label = ctk.CTkLabel(bar, text="Liste yüklenmedi", text_color=theme.TEXT_DIM,
                                      font=(theme.FONT_FAMILY, 11))
        self.ond_label.pack(anchor="w", padx=12)

        # --- Dinamik Rota Oluşturucu (OND + taşıyıcı elle) --- #
        self._section(bar, "Rota Oluşturucu")
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 2))
        self.rb_airline = ctk.CTkEntry(row, placeholder_text="Taşıyıcı (TK,AF)", width=110,
                                       fg_color=theme.BG_CARD, border_color=theme.BORDER)
        self.rb_airline.pack(side="left", padx=(0, 4))
        self.rb_origin = ctk.CTkEntry(row, placeholder_text="Origin", width=66,
                                      fg_color=theme.BG_CARD, border_color=theme.BORDER)
        self.rb_origin.pack(side="left", padx=(0, 4))
        self.rb_dest = ctk.CTkEntry(row, placeholder_text="Dest", width=66,
                                    fg_color=theme.BG_CARD, border_color=theme.BORDER)
        self.rb_dest.pack(side="left")
        ctk.CTkButton(bar, text="➕  Rota Ekle", command=self._add_route,
                      fg_color=theme.PRIMARY, hover_color=theme.PRIMARY_HOVER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=(4, 4))
        self.ond_listbox = Listbox(bar, height=6, bg=theme.BG_CARD, fg=theme.TEXT,
                                   selectbackground=theme.PRIMARY, selectforeground="#FFFFFF",
                                   highlightthickness=1, highlightbackground=theme.BORDER,
                                   borderwidth=0, font=(theme.FONT_MONO, 10), activestyle="none")
        self.ond_listbox.pack(fill="x", padx=12, pady=(0, 2))
        rmrow = ctk.CTkFrame(bar, fg_color="transparent")
        rmrow.pack(fill="x", padx=12, pady=(0, 2))
        ctk.CTkButton(rmrow, text="🗑 Seçiliyi Sil", command=self._remove_selected_route,
                      width=120, fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(side="left", padx=(0, 6))
        ctk.CTkButton(rmrow, text="Temizle", command=self._clear_routes,
                      width=90, fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(side="left")

        self._section(bar, "Filtreler")
        self.airline_filter = self._entry(bar, "Havayolu filtresi (örn: TK,AF)")
        self.origin_filter = self._entry(bar, "Origin filtresi")
        self.dest_filter = self._entry(bar, "Destination filtresi")

        self._section(bar, "Uçuş / Toplama")
        self.date_entry = self._entry(bar, "Uçuş tarihi (YYYY-MM-DD)")
        if CONFIG.default_travel_date:
            self.date_entry.insert(0, CONFIG.default_travel_date)

        self._section(bar, "Çalışma Modu")
        self.demo_var = ctk.BooleanVar(value=CONFIG.demo_mode)
        ctk.CTkSwitch(bar, text="Demo modu (çevrimdışı, sahte veri)", variable=self.demo_var,
                      progress_color=theme.PRIMARY).pack(anchor="w", padx=12, pady=4)
        self.headless_var = ctk.BooleanVar(value=CONFIG.headless)
        ctk.CTkSwitch(bar, text="Headless mod", variable=self.headless_var,
                      progress_color=theme.PRIMARY).pack(anchor="w", padx=12, pady=4)
        self.resume_var = ctk.BooleanVar(value=CONFIG.resume)
        ctk.CTkSwitch(bar, text="Resume (kaldığı yerden)", variable=self.resume_var,
                      progress_color=theme.PRIMARY).pack(anchor="w", padx=12, pady=4)
        self.skip_var = ctk.BooleanVar(value=CONFIG.skip_existing)
        ctk.CTkSwitch(bar, text="Var olanı tekrar çekme", variable=self.skip_var,
                      progress_color=theme.PRIMARY).pack(anchor="w", padx=12, pady=4)

        self.due_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(bar, text="Sadece zamanı gelenler\n(Local: haftalık, Beyond: aylık)",
                      variable=self.due_var,
                      progress_color=theme.PRIMARY).pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(bar, text="Thread sayısı", text_color=theme.TEXT_DIM,
                     font=(theme.FONT_FAMILY, 11)).pack(anchor="w", padx=12, pady=(8, 0))
        self.thread_slider = ctk.CTkSlider(bar, from_=1, to=12, number_of_steps=11,
                                           command=self._on_thread_change, progress_color=theme.PRIMARY)
        self.thread_slider.set(CONFIG.max_workers)
        self.thread_slider.pack(fill="x", padx=12)
        self.thread_label = ctk.CTkLabel(bar, text=f"{CONFIG.max_workers} taşıyıcı paralel",
                                         text_color=theme.TEXT, font=(theme.FONT_FAMILY, 11))
        self.thread_label.pack(anchor="w", padx=12)

        ctk.CTkLabel(bar, text="Tarayıcı başına sekme (eşzamanlı sorgu)", text_color=theme.TEXT_DIM,
                     font=(theme.FONT_FAMILY, 11)).pack(anchor="w", padx=12, pady=(8, 0))
        self.tabs_slider = ctk.CTkSlider(bar, from_=1, to=12, number_of_steps=11,
                                         command=self._on_tabs_change, progress_color=theme.PRIMARY)
        self.tabs_slider.set(CONFIG.pages_per_browser)
        self.tabs_slider.pack(fill="x", padx=12)
        self.tabs_label = ctk.CTkLabel(bar, text=f"{CONFIG.pages_per_browser} sekme",
                                       text_color=theme.TEXT, font=(theme.FONT_FAMILY, 11))
        self.tabs_label.pack(anchor="w", padx=12)

        self._section(bar, "Çıktı")
        ctk.CTkButton(bar, text="📂  Çıktı Klasörü Seç", command=self._pick_output,
                      fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=6)
        self.output_label = ctk.CTkLabel(bar, text=str(CONFIG.output_dir), text_color=theme.TEXT_DIM,
                                         font=(theme.FONT_MONO, 10), wraplength=250, justify="left")
        self.output_label.pack(anchor="w", padx=12)

        self._section(bar, "")
        self.start_btn = ctk.CTkButton(bar, text="▶  START", command=self._start,
                                       fg_color=theme.OK, hover_color="#2FB985",
                                       font=(theme.FONT_FAMILY, 14, "bold"), height=42,
                                       corner_radius=theme.CORNER)
        self.start_btn.pack(fill="x", padx=12, pady=(6, 4))
        self.stop_btn = ctk.CTkButton(bar, text="■  STOP", command=self._stop,
                                      fg_color=theme.FAIL, hover_color="#E05555",
                                      state="disabled", corner_radius=theme.CORNER)
        self.stop_btn.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(bar, text="🌐  HTML Panelini Aç", command=self._open_dashboard,
                      fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(bar, text="📡  Paneli Canlı Yayınla", command=self._publish_panel,
                      fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(bar, text="⬇  TSV Export (ham veri)", command=self._export_tsv,
                      fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(bar, text="🗄  Archive", command=self._open_archive,
                      fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                      text_color=theme.TEXT, border_width=1, border_color=theme.BORDER,
                      corner_radius=theme.CORNER).pack(fill="x", padx=12, pady=4)

    def _build_center(self) -> None:
        center = ctk.CTkFrame(self, fg_color=theme.BG_DEEP, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew", padx=(0, 0))
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(center, fg_color=theme.BG_DEEP)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(header, text="FARE FAMILY MATRIX", font=(theme.FONT_FAMILY, 18, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        self.count_label = ctk.CTkLabel(header, text="0 paket", text_color=theme.PRIMARY,
                                        font=(theme.FONT_MONO, 12))
        self.count_label.pack(side="right")

        # ttk.Treeview'i koyu temaya uydur
        self._style_tree()
        cols = ("Airline", "O-D", "Cabin", "Fare Brand", "Class", "Price", "Cur",
                "Checked Bag", "Seat", "Refund", "Change", "Lounge", "Order", "Source")
        self.tree = ttk.Treeview(center, columns=cols, show="headings", style="Fare.Treeview")
        widths = (60, 90, 130, 150, 50, 80, 45, 100, 90, 90, 90, 90, 55, 80)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
        vsb = ttk.Scrollbar(center, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns", pady=(4, 12))

    def _build_log_panel(self) -> None:
        panel = ctk.CTkFrame(self, width=340, fg_color=theme.BG_PANEL, corner_radius=0)
        panel.grid(row=0, column=2, sticky="nse", rowspan=2)
        panel.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(panel, text="●  CANLI LOG", font=(theme.FONT_FAMILY, 14, "bold"),
                     text_color=theme.OK).grid(row=0, column=0, sticky="w", padx=12, pady=(14, 6))
        self.log_box = ctk.CTkTextbox(panel, width=320, fg_color=theme.BG_DEEP,
                                      text_color=theme.TEXT, font=(theme.FONT_MONO, 11),
                                      corner_radius=theme.CORNER)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

    def _build_bottom_bar(self) -> None:
        bottom = ctk.CTkFrame(self, height=48, fg_color=theme.BG_PANEL, corner_radius=0)
        bottom.grid(row=1, column=1, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(bottom, progress_color=theme.PRIMARY, height=14)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        self.summary_label = ctk.CTkLabel(bottom, text="Hazır", text_color=theme.TEXT_DIM,
                                          font=(theme.FONT_MONO, 11))
        self.summary_label.grid(row=0, column=1, padx=12)

    # ------------------------------------------------------------------ #
    # Küçük yardımcılar
    # ------------------------------------------------------------------ #
    def _section(self, parent, title: str) -> None:
        ctk.CTkLabel(parent, text=title.upper(), text_color=theme.TEXT_DIM,
                     font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=12, pady=(14, 2))

    def _entry(self, parent, placeholder: str) -> ctk.CTkEntry:
        e = ctk.CTkEntry(parent, placeholder_text=placeholder, fg_color=theme.BG_CARD,
                         border_color=theme.BORDER, corner_radius=theme.CORNER)
        e.pack(fill="x", padx=12, pady=4)
        return e

    def _style_tree(self) -> None:
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Fare.Treeview", background=theme.BG_CARD, fieldbackground=theme.BG_CARD,
                        foreground=theme.TEXT, rowheight=26, borderwidth=0,
                        font=(theme.FONT_MONO, 10))
        style.configure("Fare.Treeview.Heading", background=theme.BG_PANEL, foreground=theme.PRIMARY,
                        font=(theme.FONT_FAMILY, 10, "bold"), borderwidth=0)
        style.map("Fare.Treeview", background=[("selected", theme.PRIMARY)])

    # ------------------------------------------------------------------ #
    # Olaylar
    # ------------------------------------------------------------------ #
    def _on_thread_change(self, value: float) -> None:
        self.thread_label.configure(text=f"{int(value)} taşıyıcı paralel")

    def _on_tabs_change(self, value: float) -> None:
        self.tabs_label.configure(text=f"{int(value)} sekme")

    def _load_ond(self) -> None:
        path = filedialog.askopenfilename(
            title="OND listesi seç (CSV/Excel — OND + taşıyıcı)",
            filetypes=[("Veri dosyaları", "*.csv *.xlsx *.xls"), ("Tümü", "*.*")],
        )
        if not path:
            return
        try:
            loaded = load_ond_file(path)
            added = self._merge_onds(loaded)
            self._append_log(f"OND dosyası yüklendi: {len(loaded)} kayıt ({added} yeni).")
        except Exception as exc:  # noqa: BLE001
            self.ond_label.configure(text=f"Hata: {exc}", text_color=theme.FAIL)
            self._append_log(f"⚠ OND yükleme hatası: {exc}")

    # ---- Dinamik rota yönetimi ---- #
    def _merge_onds(self, new: list[OND]) -> int:
        """Yeni OND'leri mevcut listeye tekilleştirerek ekler; eklenen sayısı."""
        existing = {o.key for o in self.onds}
        added = 0
        for o in new:
            if o.key not in existing:
                existing.add(o.key)
                self.onds.append(o)
                added += 1
        self._refresh_ond_list()
        return added

    def _refresh_ond_list(self) -> None:
        self.ond_listbox.delete(0, "end")
        for o in self.onds:
            self.ond_listbox.insert("end", f"{o.airline}  {o.origin}-{o.destination}")
        n = len(self.onds)
        self.ond_label.configure(
            text=(f"{n} OND hazır ✔" if n else "Liste boş — rota ekleyin veya dosya yükleyin"),
            text_color=(theme.OK if n else theme.TEXT_DIM),
        )

    def _add_route(self) -> None:
        try:
            onds = ond_from_fields(self.rb_airline.get(), self.rb_origin.get(), self.rb_dest.get())
        except ValueError as exc:
            self._append_log(f"⚠ {exc}")
            return
        added = self._merge_onds(onds)
        self._append_log(f"Rota eklendi: {', '.join(str(o) for o in onds)} ({added} yeni).")
        self.rb_airline.delete(0, "end")
        self.rb_origin.delete(0, "end")
        self.rb_dest.delete(0, "end")

    def _remove_selected_route(self) -> None:
        sel = list(self.ond_listbox.curselection())
        if not sel:
            self._append_log("⚠ Silmek için listeden bir rota seçin.")
            return
        for idx in sorted(sel, reverse=True):
            if 0 <= idx < len(self.onds):
                del self.onds[idx]
        self._refresh_ond_list()

    def _clear_routes(self) -> None:
        self.onds.clear()
        self._refresh_ond_list()

    def _pick_output(self) -> None:
        d = filedialog.askdirectory(title="Çıktı klasörü seç")
        if d:
            CONFIG.output_dir = Path(d)
            CONFIG.output_dir.mkdir(parents=True, exist_ok=True)
            self.output_label.configure(text=str(CONFIG.output_dir))

    def _apply_filters(self) -> list[OND]:
        """Sidebar filtrelerini OND listesine uygular."""
        def _split(entry: ctk.CTkEntry) -> set[str]:
            return {x.strip().upper() for x in entry.get().split(",") if x.strip()}

        airlines, origins, dests = _split(self.airline_filter), _split(self.origin_filter), _split(self.dest_filter)
        result = []
        for o in self.onds:
            if airlines and o.airline not in airlines:
                continue
            if origins and o.origin not in origins:
                continue
            if dests and o.destination not in dests:
                continue
            result.append(o)
        return result

    def _sync_config(self) -> None:
        """Arayüz kontrollerini CONFIG'e yansıtır."""
        CONFIG.demo_mode = self.demo_var.get()
        CONFIG.headless = self.headless_var.get()
        CONFIG.resume = self.resume_var.get()
        CONFIG.skip_existing = self.skip_var.get()
        CONFIG.max_workers = int(self.thread_slider.get())
        CONFIG.pages_per_browser = int(self.tabs_slider.get())
        date_val = self.date_entry.get().strip()
        if date_val:
            CONFIG.default_travel_date = date_val

    def _start(self) -> None:
        if not self.onds:
            self._append_log("⚠ Önce OND listesi yükleyin.")
            return
        if self._worker and self._worker.is_alive():
            return

        self._sync_config()
        targets = self._apply_filters()
        if not targets:
            self._append_log("⚠ Filtrelere uyan OND yok.")
            return

        self.fares.clear()
        self.tree.delete(*self.tree.get_children())
        self.progress.set(0)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.summary_label.configure(text="Çalışıyor…", text_color=theme.ACCENT_AMBER)

        self.runner = CollectorRunner(
            CONFIG,
            on_progress=self._on_progress,
            on_log=self._append_log,
            on_result=self._on_result,
        )
        if not CONFIG.resume:
            self.runner.reset_resume()

        self._worker = threading.Thread(target=self._run_worker, args=(targets,), daemon=True)
        self._worker.start()

    def _run_worker(self, targets: list[OND]) -> None:
        try:
            fares, summary = self.runner.run(
                targets, CONFIG.default_travel_date or None,
                only_due=self.due_var.get(),
            )
            from core.exporter import Exporter
            written = Exporter(CONFIG).export_all(fares)
            self.after(0, lambda: self._on_finish(summary, written))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._append_log(f"Çalışma hatası: {exc}"))
            self.after(0, self._reset_buttons)

    def _stop(self) -> None:
        if self.runner:
            self.runner.stop()
            self._append_log("Durdurma istendi…")

    # ------------------------------------------------------------------ #
    # Callback'ler (thread'den gelir; after ile UI thread'e taşınır)
    # ------------------------------------------------------------------ #
    def _on_progress(self, done: int, total: int) -> None:
        self.after(0, lambda: self.progress.set(done / total if total else 0))

    def _on_result(self, ond: OND, fares: list[FareBrand]) -> None:
        self.after(0, lambda: self._add_rows(fares))

    def _add_rows(self, fares: list[FareBrand]) -> None:
        for f in fares:
            feats = f.features
            self.tree.insert("", "end", values=(
                f.airline, f"{f.origin}-{f.destination}", f.cabin, f.fare_brand,
                f.booking_class, f.price if f.price is not None else "-", f.currency,
                _cell(feats, "checked_baggage"), _cell(feats, "seat_selection"),
                _cell(feats, "refund"), _cell(feats, "change"), _cell(feats, "lounge"),
                f.package_order, f.source or "-",
            ))
        self.fares.extend(fares)
        self.count_label.configure(text=f"{len(self.fares)} paket")

    def _on_finish(self, summary: RunSummary, written: dict) -> None:
        self._reset_buttons()
        paths = ", ".join(str(p.name) for p in written.values()) or "-"
        self.summary_label.configure(
            text=f"✔ {summary.success} OK · {summary.failed} FAIL · "
                 f"{summary.total_fares} fare · {summary.duration_seconds:.0f}s",
            text_color=theme.OK,
        )
        self._append_log(f"Dosyalar yazıldı: {paths}")

    def _reset_buttons(self) -> None:
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Log
    # ------------------------------------------------------------------ #
    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        """Logging kuyruğunu periyodik boşaltır (canlı log)."""
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(200, self._poll_log_queue)

    def _open_dashboard(self) -> None:
        """HTML panelini varsayılan tarayıcıda açar."""
        dash = Path(__file__).resolve().parent.parent / "web" / "index.html"
        if dash.exists():
            webbrowser.open(dash.as_uri())
        else:
            self._append_log("HTML paneli bulunamadı (web/index.html).")

    def _publish_panel(self) -> None:
        """Paneli `output/` üzerinden basit bir HTTP sunucusuyla canlı yayınlar.

        `web/index.html` çıktı klasörüne kopyalanır ve arka planda (daemon
        thread) bir HTTP sunucusu başlatılır. Panel "canlı" modda `data.json`'u
        periyodik yenilediğinden, yeni çekimler tarayıcıda otomatik görünür.
        Ağdaki başka cihazlar da `http://<makine-ip>:<port>/index.html` ile erişir.
        """
        import functools
        import http.server
        import shutil
        import socketserver

        out = CONFIG.output_dir
        out.mkdir(parents=True, exist_ok=True)
        src = Path(__file__).resolve().parent.parent / "web" / "index.html"
        if src.exists():
            try:
                shutil.copy(src, out / "index.html")
            except OSError as exc:
                self._append_log(f"⚠ Panel kopyalanamadı: {exc}")

        if self._httpd is None:
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
            port = None
            for candidate in (8080, 8090, 0):  # 0 → işletim sistemi boş port seçer
                try:
                    self._httpd = socketserver.ThreadingTCPServer(("", candidate), handler)
                    port = self._httpd.server_address[1]
                    break
                except OSError:
                    continue
            if self._httpd is None:
                self._append_log("⚠ Panel sunucusu başlatılamadı (uygun port yok).")
                return
            self._panel_port = port
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
            self._append_log(f"📡 Panel yayında: http://localhost:{port}/index.html "
                             f"(ağda: http://<makine-ip>:{port}/index.html)")
        webbrowser.open(f"http://localhost:{self._panel_port}/index.html")

    def _export_tsv(self) -> None:
        """Mevcut (son çekilen) ham veriyi tek tıkla TSV olarak dışa aktarır.

        Ekranda filtrelenmiş görünüm varsa bile ham verinin tamamı yazılır;
        filtreli export için Archive/HTML panelindeki indirme kullanılabilir.
        """
        if not self.fares:
            self._append_log("⚠ Export edilecek veri yok. Önce bir çekim yapın.")
            return
        from tkinter import filedialog

        from core.exporter import Exporter
        path = filedialog.asksaveasfilename(
            title="TSV olarak kaydet",
            defaultextension=".tsv",
            filetypes=[("TSV", "*.tsv"), ("Tüm dosyalar", "*.*")],
            initialfile="fares_raw.tsv",
        )
        if not path:
            return
        Exporter(CONFIG).to_tsv(self.fares, path=Path(path))
        self._append_log(f"TSV kaydedildi: {path}")

    def _open_archive(self) -> None:
        """Archive penceresi: geçmiş çekimler + indirme/görüntüleme.

        Her satır bir çekimi temsil eder (CollDate, zaman, havayolları,
        OND sayısı, kayıt sayısı, durum). Seçili çekim için TSV/Excel/
        SQLite dosyaları klasöründen açılabilir, ham veri görüntülenebilir.
        """
        from core.exporter import Exporter
        index = Exporter(CONFIG).load_archive_index()

        win = ctk.CTkToplevel(self)
        win.title("Archive — Geçmiş Veri Çekimleri")
        win.geometry("860x480")
        win.configure(fg_color=theme.BG_DEEP)

        cols = ("colldate", "time", "airlines", "onds", "records", "status")
        tree = ttk.Treeview(win, columns=cols, show="headings",
                            style="Fare.Treeview", height=14)
        for cid, text, width in (
            ("colldate", "CollDate", 100), ("time", "Çekim Zamanı", 150),
            ("airlines", "Havayolları", 200), ("onds", "OND", 70),
            ("records", "Kayıt", 70), ("status", "Durum", 80),
        ):
            tree.heading(cid, text=text)
            tree.column(cid, width=width, anchor="w")
        for run in reversed(index):
            tree.insert("", "end", iid=run["run_id"], values=(
                run.get("coll_date", ""), run.get("collected_at", ""),
                ", ".join(run.get("airlines", []))[:40],
                len(run.get("onds", [])), run.get("record_count", 0),
                run.get("status", ""),
            ))
        tree.pack(fill="both", expand=True, padx=12, pady=12)

        def _run_dir() -> Path | None:
            sel = tree.selection()
            if not sel:
                self._append_log("⚠ Önce bir çekim seçin.")
                return None
            d = CONFIG.output_dir / "archive" / sel[0]
            if not d.exists():
                self._append_log(f"⚠ Arşiv klasörü bulunamadı: {d}")
                return None
            return d

        def _open_file(name: str) -> None:
            d = _run_dir()
            if d and (d / name).exists():
                webbrowser.open((d / name).as_uri())

        btns = ctk.CTkFrame(win, fg_color=theme.BG_PANEL)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        for label, fname in (("⬇ TSV indir", "raw.tsv"), ("⬇ Excel indir", "fares.xlsx"),
                             ("⬇ SQLite indir", "fares.db"), ("👁 Ham veriyi görüntüle", "raw.tsv")):
            ctk.CTkButton(btns, text=label, width=170,
                          command=lambda f=fname: _open_file(f),
                          fg_color=theme.BG_CARD, hover_color=theme.BORDER,
                          text_color=theme.TEXT, border_width=1,
                          border_color=theme.BORDER).pack(side="left", padx=6, pady=8)


def launch() -> None:
    """Uygulamayı başlatır."""
    app = FareCollectorApp()
    app.mainloop()


def _cell(features: dict, name: str) -> str:
    f = features.get(name)
    return f.to_cell() if f else "-"
