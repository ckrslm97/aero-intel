"""Arayüz tema sabitleri.

Tamamen BEYAZ tema: okunabilirlik, sadelik ve profesyonel görünüm
önceliklidir. Renkler tek yerde tutulur; arayüz bileşenleri buradan
okur (magic color kullanılmaz). Değişken adları korunmuştur, böylece
tema tek dosyadan değiştirilebilir.
"""
from __future__ import annotations

# Ana palet (beyaz tema)
BG_DEEP = "#FFFFFF"        # en arka plan
BG_PANEL = "#F6F8FB"       # yan panel / başlık arka planı
BG_CARD = "#FFFFFF"        # kart / giriş kutusu
BORDER = "#E2E8F0"

TEXT = "#1A2433"
TEXT_DIM = "#64748B"

PRIMARY = "#1D6FE0"        # kurumsal mavi
PRIMARY_HOVER = "#1558B8"
ACCENT_AMBER = "#D97706"   # uyarı / vurgular
OK = "#0E9F6E"
FAIL = "#DC2626"

# Kabin renk kodları (HTML paneliyle uyumlu)
CABIN_COLORS = {
    "Economy": "#1D6FE0",
    "Premium Economy": "#7C3AED",
    "Business": "#D97706",
    "First": "#DC2626",
    "Unknown": "#64748B",
}

# Boyut sabitleri
CORNER = 8
PAD = 8
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"
