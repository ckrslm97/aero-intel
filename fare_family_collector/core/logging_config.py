"""Merkezi logging yapılandırması.

Hem dosyaya hem de arayüzdeki canlı log ekranına yazabilmek için
özel bir handler (``QueueLogHandler``) sağlar. GUI bu kuyruğu periyodik
olarak okur ve log kutusuna basar.
"""
from __future__ import annotations

import logging
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


class QueueLogHandler(logging.Handler):
    """Log kayıtlarını bir kuyruğa iterek GUI'nin okumasını sağlar."""

    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put_nowait(self.format(record))
        except queue.Full:  # pragma: no cover - kuyruk doluysa sessiz geç
            pass


def setup_logging(
    log_dir: str | Path = "logs",
    level: int = logging.INFO,
    log_queue: "queue.Queue[str] | None" = None,
) -> logging.Logger:
    """Kök logger'ı yapılandırır.

    Args:
        log_dir: Log dosyalarının yazılacağı klasör.
        level: Log seviyesi.
        log_queue: Verilirse GUI için kuyruk handler'ı da eklenir.

    Returns:
        Yapılandırılmış kök logger.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    root = logging.getLogger("fff")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        log_dir / "collector.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_queue is not None:
        qh = QueueLogHandler(log_queue)
        qh.setFormatter(formatter)
        root.addHandler(qh)

    return root


def get_logger(name: str) -> logging.Logger:
    """Alt-logger döndürür (örn. ``get_logger('scraper.tk')``)."""
    return logging.getLogger(f"fff.{name}")
