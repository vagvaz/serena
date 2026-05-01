"""Concurrency tests for ReadWriteLock and TaskExecutor.

Uses ``threading.Barrier`` to force deterministic interleaving at known points,
so we can verify reader/writer exclusion properties without relying on timing.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from serena.task_executor import ReadWriteLock, TaskExecutor
from serena.util.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


# ── ReadWriteLock tests ──────────────────────────────────────────────────


class TestReadWriteLock:
    """Tests for the reader-writer lock used by TaskExecutor."""

    def test_multiple_readers_concurrent(self):
        """Multiple readers can hold the lock simultaneously."""
        lock = ReadWriteLock()
        barrier = threading.Barrier(3, timeout=5)  # all three threads sync here
        results: list[int] = []
        lock_results = threading.Lock()

        def reader(thread_id: int):
            lock.acquire_read()
            try:
                # All readers arrive at the barrier — if the lock allowed
                # concurrent reads, all 3 threads will pass.  If not, at
                # least one will time out.
                barrier.wait()
                with lock_results:
                    results.append(thread_id)
            finally:
                lock.release_read()

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        with lock_results:
            assert len(results) == 3, f"Expected 3 concurrent readers, got {len(results)}"

    def test_writer_excludes_readers(self):
        """A writer blocks new readers until the writer releases."""
        lock = ReadWriteLock()
        started_writing = threading.Event()
        can_release = threading.Event()

        def writer():
            lock.acquire_write()
            try:
                started_writing.set()
                can_release.wait(timeout=5)
            finally:
                lock.release_write()

        writer_thread = threading.Thread(target=writer)
        writer_thread.start()

        started_writing.wait(timeout=5)  # writer has the write lock

        # Try to acquire a read lock — should block
        read_acquired = threading.Event()

        def reader():
            lock.acquire_read()
            read_acquired.set()
            lock.release_read()

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()
        time.sleep(0.05)  # small delay to let the reader block
        assert not read_acquired.is_set(), "Reader should be blocked by writer"

        # Release the writer
        can_release.set()
        writer_thread.join(timeout=2)
        # Now the reader should get through
        read_acquired.wait(timeout=2)
        assert read_acquired.is_set()
        reader_thread.join(timeout=1)

    def test_writer_excludes_writers(self):
        """A writer blocks other writers until it releases."""
        lock = ReadWriteLock()
        started_writing = threading.Event()
        can_release = threading.Event()

        def writer_1():
            lock.acquire_write()
            started_writing.set()
            can_release.wait(timeout=5)
            lock.release_write()

        t1 = threading.Thread(target=writer_1)
        t1.start()
        started_writing.wait(timeout=5)

        # Try to acquire write from another thread — should block
        writer2_acquired = threading.Event()

        def writer_2():
            lock.acquire_write()
            writer2_acquired.set()
            lock.release_write()

        t2 = threading.Thread(target=writer_2)
        t2.start()
        time.sleep(0.05)
        assert not writer2_acquired.is_set(), "Writer 2 should be blocked by writer 1"

        # Release writer 1
        can_release.set()
        t1.join(timeout=2)
        writer2_acquired.wait(timeout=2)
        assert writer2_acquired.is_set()
        t2.join(timeout=1)


class TestTaskExecutorConcurrency:
    """Tests for TaskExecutor project-level read/write locking."""

    def test_concurrent_reads_same_project(self):
        """Read-only tasks for the same project run concurrently."""
        executor = TaskExecutor("test-concurrent-reads", max_workers=4)
        barrier = threading.Barrier(3, timeout=5)
        results: list[int] = []
        lock = threading.Lock()

        def read_task(thread_id: int) -> int:
            barrier.wait()
            with lock:
                results.append(thread_id)
            return thread_id

        t1 = executor.issue_task(lambda: read_task(1), name="r1", project="proj", read_only=True)
        t2 = executor.issue_task(lambda: read_task(2), name="r2", project="proj", read_only=True)
        t3 = executor.issue_task(lambda: read_task(3), name="r3", project="proj", read_only=True)

        t1.result(timeout=5)
        t2.result(timeout=5)
        t3.result(timeout=5)

        assert len(results) == 3, f"Expected 3 concurrent reads, got {len(results)}"
        executor.shutdown()

    def test_write_excludes_read_same_project(self):
        """A write task blocks read tasks for the same project."""
        executor = TaskExecutor("test-write-excludes-read", max_workers=4)
        write_started = threading.Event()
        can_release = threading.Event()
        read_executed = threading.Event()

        def write_task() -> str:
            write_started.set()
            can_release.wait(timeout=5)
            return "written"

        def read_task() -> str:
            read_executed.set()
            return "read"

        w = executor.issue_task(write_task, name="write1", project="proj", read_only=False)
        write_started.wait(timeout=5)

        # Read task for same project should be queued (not yet running)
        r = executor.issue_task(read_task, name="read1", project="proj", read_only=True)
        time.sleep(0.05)
        assert not read_executed.is_set(), "Read should be blocked by write"

        # Release the write
        can_release.set()
        assert w.result(timeout=5) == "written"
        assert r.result(timeout=5) == "read"
        assert read_executed.is_set()
        executor.shutdown()

    def test_independent_projects_run_in_parallel(self):
        """Tasks for different projects are independent."""
        executor = TaskExecutor("test-independent", max_workers=4)
        barrier = threading.Barrier(3, timeout=5)
        results: list[str] = []
        lock = threading.Lock()

        def task(name: str) -> str:
            barrier.wait()
            with lock:
                results.append(name)
            return name

        t1 = executor.issue_task(lambda: task("proj-a-r1"), name="a", project="proj-a", read_only=False)
        t2 = executor.issue_task(lambda: task("proj-b-r1"), name="b", project="proj-b", read_only=False)
        t3 = executor.issue_task(lambda: task("proj-c-r1"), name="c", project="proj-c", read_only=True)

        t1.result(timeout=5)
        t2.result(timeout=5)
        t3.result(timeout=5)

        # All 3 should have run (different projects → no mutual exclusion)
        assert len(results) == 3, f"Expected 3 independent tasks, got {len(results)}"
        executor.shutdown()

    def test_write_serialized_same_project(self):
        """Write tasks for the same project are serialized (not concurrent)."""
        executor = TaskExecutor("test-serialized-writes", max_workers=4)
        counter = 0
        counter_lock = threading.Lock()
        max_concurrent = 0
        active = 0
        active_lock = threading.Lock()

        def write_task() -> int:
            nonlocal active, max_concurrent
            with active_lock:
                active += 1
                max_concurrent = max(max_concurrent, active)
            time.sleep(0.1)
            with active_lock:
                active -= 1
            with counter_lock:
                nonlocal counter
                counter += 1
            return counter

        tasks = [
            executor.issue_task(write_task, name=f"w{i}", project="proj", read_only=False)
            for i in range(5)
        ]

        for t in tasks:
            t.result(timeout=5)

        # Since writes are serialized, max_concurrent should be 1
        assert max_concurrent == 1, f"Writes should be serialized, max concurrent was {max_concurrent}"
        executor.shutdown()


class TestCircuitBreaker:
    """Tests for the circuit breaker used by apply_ex."""

    def test_closed_by_default(self):
        """A new circuit breaker starts closed."""
        cb = CircuitBreaker("test")
        assert not cb.is_open()

    def test_opens_after_threshold_failures(self):
        """After the threshold number of consecutive failures, the circuit opens."""
        cb = CircuitBreaker("test", threshold=3, backoff=60.0)
        cb.record_failure()
        assert not cb.is_open()
        cb.record_failure()
        assert not cb.is_open()
        cb.record_failure()
        assert cb.is_open()

    def test_resets_on_success(self):
        """A successful call resets the failure count."""
        cb = CircuitBreaker("test", threshold=3, backoff=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert not cb.is_open()

    def test_half_open_on_backoff_expiry(self):
        """After the backoff period expires, the circuit transitions to half-open."""
        cb = CircuitBreaker("test", threshold=1, backoff=0.05)
        cb.record_failure()
        assert cb.is_open()

        # Wait for backoff to expire
        time.sleep(0.06)
        # is_open() should return False (half-open transition)
        assert not cb.is_open()

    def test_open_blocks_calls(self):
        """When the circuit is open, calls are blocked with CircuitBreakerOpenError."""
        cb = CircuitBreaker("test", threshold=1, backoff=60.0)
        cb.record_failure()
        assert cb.is_open()

        # Simulate what apply_ex does when the circuit is open
        with pytest.raises(CircuitBreakerOpenError):
            if cb.is_open():
                raise CircuitBreakerOpenError()

    def test_manual_reset(self):
        """reset() manually closes an open circuit breaker."""
        cb = CircuitBreaker("test", threshold=1, backoff=60.0)
        cb.record_failure()
        assert cb.is_open()

        cb.reset()
        assert not cb.is_open()

    def test_record_failure_returns_trip_flag(self):
        """record_failure returns True whenever the count is >= threshold."""
        cb = CircuitBreaker("test", threshold=2, backoff=60.0)
        assert cb.record_failure() is False  # below threshold
        assert cb.record_failure() is True   # at threshold → trip
        assert cb.record_failure() is True   # above threshold → still tripped
