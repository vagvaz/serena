"""Per-language-server circuit breaker to prevent repeated restart loops.

When a language server crashes repeatedly within a short window the circuit
trips and further calls are rejected immediately with ``LS_CIRCUIT_OPEN``
until the backoff period expires.
"""

import time
import threading
import logging

log = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the circuit breaker is open."""


class CircuitBreaker:
    """Tracks failure counts per language server.

    State machine::

        CLOSED ──(threshold exceeded)──▶ OPEN
           ▲                               │
           │        (backoff expired)       │
           └──────── HALF_OPEN ◄────────────┘
                         │
                    (call succeeds) ──▶ CLOSED

    Thread-safe.
    """

    def __init__(self, name: str, threshold: int = 3, backoff: float = 30.0) -> None:
        """
        :param name: Human-readable label (e.g. ``"python"``).
        :param threshold: Number of consecutive failures before tripping.
        :param backoff: Seconds to stay open before transitioning to half-open.
        """
        self._name = name
        self._threshold = threshold
        self._backoff = backoff
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._open = threading.Event()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    # -- public query / mutate helpers used by the tool pipeline -----------

    def is_open(self) -> bool:
        """Returns True if the circuit is currently open.

        Automatically transitions to half-open if the backoff has expired.
        """
        if not self._open.is_set():
            return False
        # Backoff expired → half-open (let one call through)
        if time.monotonic() - self._last_failure_time >= self._backoff:
            self._open.clear()
            log.info("Circuit breaker '%s' transitioning to half-open", self._name)
            return False
        return True

    def record_success(self) -> None:
        """Call after a successful LS operation to reset the failure count."""
        with self._lock:
            self._failure_count = 0
            self._open.clear()

    def record_failure(self) -> bool:
        """Call after an LS crash.

        :returns: True if the circuit just tripped (threshold crossed).
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._threshold:
                self._open.set()
                log.warning(
                    "Circuit breaker '%s' OPEN after %d failures (backoff=%ss)",
                    self._name, self._failure_count, self._backoff,
                )
                return True
        return False

    def reset(self) -> None:
        """Manually reset the circuit breaker (e.g. on explicit LS restart)."""
        with self._lock:
            self._failure_count = 0
            self._open.clear()
        log.info("Circuit breaker '%s' manually reset", self._name)
