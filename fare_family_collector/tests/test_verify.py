"""Girdi-doğrulama eşleştiricisinin (input_matches) testleri."""
from __future__ import annotations

import pytest

from core.verify import input_matches


@pytest.mark.parametrize("expected,actual,ok", [
    # Otomatik tamamlama dönüşümleri
    ("IST", "Istanbul (IST)", True),
    ("LHR", "London Heathrow (LHR)", True),
    ("LHR", "LHR", True),
    # Boş alan = başarısız giriş
    ("IST", "", False),
    # Yanlış değer
    ("IST", "London (LON)", False),
    # Doğrulanacak bir şey yok
    ("", "anything", True),
    # Tarih: farklı biçimler toleranslı
    ("2026-08-01", "01/08/2026", True),
    ("2026-08-01", "Sat, 1 Aug 2026", True),
    ("2026-08-01", "1 Ağu 2026", True),
    # Tarih: yanlış ay/gün → başarısız
    ("2026-08-01", "2026-09-01", False),
    ("2026-08-01", "2026-08-02", False),
])
def test_input_matches(expected, actual, ok):
    assert input_matches(expected, actual) is ok
