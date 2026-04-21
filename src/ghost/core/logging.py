"""
Non-blocking operational logging.

Uses QueueHandler → background thread → RotatingFileHandler.
The event loop never touches disk. All log formatting and file I/O
happens in the QueueListener's background thread.

This is DIFFERENT from the audit log (which is in SQLite):
- Operational log: HOW Ghost did things (stack traces, timing, debug info)
- Audit log: WHAT Ghost did (semantic events like "tool forged")

Edge case from final_bug_sweep.md:
QueueHandler + QueueListener ensure log rotation (file I/O) never blocks
the asyncio event loop — even during log bursts or slow disk flushes.
"""
import logging
import queue
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path

from ghost.constants import LOG_BACKUP_COUNT, LOG_FILE, LOG_FORMAT, LOG_MAX_BYTES, LOGS_DIR


def setup_logging(ghost_home: Path, log_level: str = "INFO") -> QueueListener:
    """
    Configure non-blocking logging.

    Returns the QueueListener, which MUST be stopped on shutdown:
        listener = setup_logging(config.ghost_home)
        # ... on shutdown:
        listener.stop()
    """
    log_dir = ghost_home / LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # Rotating file handler — runs entirely in the background thread
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    file_handler.setLevel(logging.DEBUG)

    # Console handler — warnings and above to stderr
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    console_handler.setLevel(logging.WARNING)

    # Unbounded queue: QueueHandler copies LogRecord into queue (non-blocking)
    log_queue: queue.Queue = queue.Queue(-1)
    queue_handler = QueueHandler(log_queue)

    # Configure root ghost logger to use the non-blocking queue handler
    root = logging.getLogger("ghost")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    # Avoid adding duplicate handlers if called more than once
    root.handlers.clear()
    root.addHandler(queue_handler)
    root.addHandler(console_handler)
    root.propagate = False

    # QueueListener drains the queue in a dedicated background thread
    listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
    listener.start()

    return listener


def set_log_level(level: str) -> None:
    """Dynamically change the log level of the ghost logger (for /api/config/log-level)."""
    root = logging.getLogger("ghost")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger(__name__).info(f"Log level changed to {level.upper()}")
