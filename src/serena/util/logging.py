import copy
import logging
import queue
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from logging import FileHandler, getLogger
from typing import Optional

from serena.constants import LOG_MESSAGES_BUFFER_SIZE, SERENA_LOG_FORMAT

# Python 3.10 compatibility: logging.getLevelNamesMapping() was added in 3.11
_LEVEL_NAMES_MAPPING: dict[str, int] | None = None


def get_level_names_mapping() -> dict[str, int]:
    """Return a mapping of level names to integer values (Python 3.10 compatible)."""
    global _LEVEL_NAMES_MAPPING
    if _LEVEL_NAMES_MAPPING is None:
        if hasattr(logging, "getLevelNamesMapping"):
            _LEVEL_NAMES_MAPPING = logging.getLevelNamesMapping()
        else:
            _LEVEL_NAMES_MAPPING = {
                "CRITICAL": logging.CRITICAL,
                "FATAL": logging.FATAL,
                "ERROR": logging.ERROR,
                "WARN": logging.WARNING,
                "WARNING": logging.WARNING,
                "INFO": logging.INFO,
                "DEBUG": logging.DEBUG,
                "NOTSET": logging.NOTSET,
            }
    return _LEVEL_NAMES_MAPPING

_log_session_id: ContextVar[str | None] = ContextVar("serena_log_session_id", default=None)
_log_project_name: ContextVar[str | None] = ContextVar("serena_log_project_name", default=None)


@contextmanager
def log_context(session_id: str | None, project_name: str | None):
    """Context manager that annotates log records with session/project metadata."""

    session_token = _log_session_id.set(session_id)
    project_token = _log_project_name.set(project_name)
    try:
        yield
    finally:
        _log_session_id.reset(session_token)
        _log_project_name.reset(project_token)


def get_current_log_session_id() -> str | None:
    return _log_session_id.get()


def get_current_log_project_name() -> str | None:
    return _log_project_name.get()


@dataclass
class LogEntry:
    message: str
    level: str
    logger_name: str
    created: float
    thread_name: str
    session_id: str | None
    project_name: str | None
    sequence: int = -1


@dataclass
class LogMessages:
    messages: list[LogEntry]
    """The list of log entries, ordered from oldest to newest."""

    max_idx: int
    """The 0-based index of the last message in ``messages``."""


class MemoryLogHandler(logging.Handler):
    def __init__(self, level: int = logging.NOTSET, max_messages: int | None = LOG_MESSAGES_BUFFER_SIZE) -> None:
        super().__init__(level=level)
        self.setFormatter(logging.Formatter(SERENA_LOG_FORMAT))
        self._log_buffer = LogBuffer(max_messages=max_messages)
        self._log_queue: queue.Queue[LogEntry] = queue.Queue()
        self._stop_event = threading.Event()
        self._emit_callbacks: list[Callable[[LogEntry], None]] = []

        # start background thread to process logs
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def add_emit_callback(self, callback: Callable[[LogEntry], None]) -> None:
        """Register a callback invoked with each processed log entry."""

        self._emit_callbacks.append(callback)

    def emit(self, record: logging.LogRecord) -> None:
        entry = self._build_entry(record)
        self._log_queue.put_nowait(entry)

    def _build_entry(self, record: logging.LogRecord) -> LogEntry:
        return LogEntry(
            message=self.format(record),
            level=record.levelname,
            logger_name=record.name,
            created=record.created,
            thread_name=record.threadName,
            session_id=get_current_log_session_id(),
            project_name=get_current_log_project_name(),
        )

    def _process_queue(self) -> None:
        while not self._stop_event.is_set():
            try:
                entry = self._log_queue.get(timeout=1)
                stored_entry = self._log_buffer.append(entry)
                for callback in self._emit_callbacks:
                    try:
                        callback(stored_entry)
                    except Exception:
                        pass
                self._log_queue.task_done()
            except queue.Empty:
                continue

    def get_log_messages(self, from_idx: int = 0) -> LogMessages:
        return self._log_buffer.get_log_messages(from_idx=from_idx)

    def clear_log_messages(self) -> None:
        self._log_buffer.clear()


class LogBuffer:
    """Thread-safe buffer for log entries."""

    def __init__(self, max_messages: int | None = None) -> None:
        self._max_messages = max_messages
        self._log_messages: list[LogEntry] = []
        self._lock = threading.Lock()
        self._max_idx = -1

    def append(self, entry: LogEntry) -> LogEntry:
        with self._lock:
            self._max_idx += 1
            entry.sequence = self._max_idx
            self._log_messages.append(entry)
            if self._max_messages is not None and len(self._log_messages) > self._max_messages:
                excess = len(self._log_messages) - self._max_messages
                self._log_messages = self._log_messages[excess:]
            return entry

    def clear(self) -> None:
        with self._lock:
            self._log_messages = []
            self._max_idx = -1

    def get_log_messages(self, from_idx: int = 0) -> LogMessages:
        from_idx = max(from_idx, 0)
        with self._lock:
            first_stored_idx = self._max_idx - len(self._log_messages) + 1
            if from_idx <= first_stored_idx:
                entries = self._log_messages.copy()
            else:
                start_idx = from_idx - first_stored_idx
                entries = self._log_messages[start_idx:].copy()
            return LogMessages(messages=[copy.copy(entry) for entry in entries], max_idx=self._max_idx)


class SuspendedLoggersContext:
    """Isolated logging environment used for temporary logging configuration."""

    def __init__(self) -> None:
        self.saved_root_handlers: list = []
        self.saved_root_level: Optional[int] = None

    def __enter__(self) -> "SuspendedLoggersContext":
        root_logger = getLogger()
        self.saved_root_handlers = root_logger.handlers.copy()
        self.saved_root_level = root_logger.level
        root_logger.handlers.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[override]
        root_logger = getLogger()
        root_logger.handlers = self.saved_root_handlers
        if self.saved_root_level is not None:
            root_logger.setLevel(self.saved_root_level)


log = getLogger(__name__)


# ── StopWatch ────────────────────────────────────────────────────────

class StopWatch:
    """
    A stop watch for timing an execution.  Constructing an instance starts it.
    """

    def __init__(self, start: bool = True) -> None:
        self.start_time = time.time()
        self._elapsed_secs = 0.0
        self.is_running = start

    def reset(self, start: bool = True) -> None:
        self.start_time = time.time()
        self._elapsed_secs = 0.0
        self.is_running = start

    def restart(self) -> None:
        self.reset(start=True)

    def _get_elapsed_time_since_last_start(self) -> float:
        if self.is_running:
            return time.time() - self.start_time
        return 0.0

    def pause(self) -> None:
        if self.is_running:
            self._elapsed_secs += self._get_elapsed_time_since_last_start()
            self.is_running = False

    def resume(self) -> None:
        if not self.is_running:
            self.start_time = time.time()
            self.is_running = True

    def get_elapsed_time_secs(self) -> float:
        if self.is_running:
            return self._elapsed_secs + self._get_elapsed_time_since_last_start()
        return self._elapsed_secs

    def get_elapsed_time_string(self) -> str:
        secs = self.get_elapsed_time_secs()
        if secs < 60:
            return f"{secs:.1f}s"
        minutes = int(secs / 60)
        secs = secs - minutes * 60
        return f"{minutes:02d}:{secs:04.1f}min"


# ── LogTime ──────────────────────────────────────────────────────────

class LogTime:
    """
    Context manager that logs execution time::

        with LogTime("Doing X"):
            do_stuff()
        # logs "Doing X ... completed in 0.42s"
    """

    def __init__(self, name: str, enabled: bool = True, logger: logging.Logger | None = None) -> None:
        self.name = name
        self.enabled = enabled
        self.stopwatch: StopWatch | None = None
        self.logger = logger or log

    def start(self) -> None:
        self.stopwatch = StopWatch()
        if self.enabled:
            self.logger.info(f"{self.name} starting ...")

    def stop(self) -> None:
        if self.stopwatch is not None and self.enabled:
            self.logger.info(f"{self.name} completed in {self.stopwatch.get_elapsed_time_string()}")

    def __enter__(self) -> "LogTime":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.stop()
        elif self.stopwatch is not None and self.enabled:
            self.logger.error(f"{self.name} failed after {self.stopwatch.get_elapsed_time_string()}")


# ── Logging helpers ──────────────────────────────────────────────────

def datetime_tag() -> str:
    """Return a compact datetime string for use in log file names."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _add_file_logger(path: str, append: bool = True) -> FileHandler:
    """Add a file handler to the root logger and return it."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handler = FileHandler(path, mode="a" if append else "w")
    getLogger().addHandler(handler)
    return handler


class FileLoggerContext:
    """Context manager that enables file-based logging within a ``with`` block."""

    def __init__(self, path: str, append: bool = True, enabled: bool = True) -> None:
        self.path = path
        self.append = append
        self.enabled = enabled
        self._handler: FileHandler | None = None

    def __enter__(self) -> FileHandler | None:
        if self.enabled:
            self._handler = _add_file_logger(self.path, append=self.append)
        return self._handler

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._handler is not None:
            getLogger().removeHandler(self._handler)
