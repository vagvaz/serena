from collections.abc import Callable
import threading
import time

import pytest

from serena.task_executor import TaskExecutor


@pytest.fixture
def executor() -> TaskExecutor:
    return TaskExecutor("TestExecutor", max_workers=4)


def _sleep_task(duration: float, *, value: str) -> Callable[[], str]:
    def _run() -> str:
        time.sleep(duration)
        return value

    return _run


def test_read_only_tasks_on_same_project_overlap(executor: TaskExecutor) -> None:
    start = time.perf_counter()
    task1 = executor.issue_task(_sleep_task(0.4, value="r1"), name="read1", project="proj", read_only=True)
    task2 = executor.issue_task(_sleep_task(0.4, value="r2"), name="read2", project="proj", read_only=True)
    assert task1.result() == "r1"
    assert task2.result() == "r2"
    duration = time.perf_counter() - start
    assert duration < 0.7, "Read-only tasks should execute concurrently on the same project"


def test_write_blocks_reads_on_same_project(executor: TaskExecutor) -> None:
    start = time.perf_counter()
    writer = executor.issue_task(_sleep_task(0.5, value="w"), name="write", project="proj", read_only=False)
    # Give the writer time to start and acquire the lock
    time.sleep(0.05)
    reader = executor.issue_task(_sleep_task(0.1, value="r"), name="read", project="proj", read_only=True)
    assert writer.result() == "w"
    assert reader.result() == "r"
    duration = time.perf_counter() - start
    assert duration >= 0.55, "Read should wait until write finishes on the same project"


def test_writes_on_distinct_projects_run_concurrently(executor: TaskExecutor) -> None:
    start = time.perf_counter()
    task1 = executor.issue_task(_sleep_task(0.5, value="a"), name="writeA", project="projA")
    task2 = executor.issue_task(_sleep_task(0.5, value="b"), name="writeB", project="projB")
    assert task1.result() == "a"
    assert task2.result() == "b"
    duration = time.perf_counter() - start
    assert duration < 0.9, "Writes on different projects should execute in parallel"


def test_exception_is_propagated(executor: TaskExecutor) -> None:
    def boom() -> None:
        raise ValueError("fail")

    task = executor.issue_task(boom, name="boom", project="proj")
    with pytest.raises(ValueError):
        task.result()


def test_task_info_contains_metadata(executor: TaskExecutor) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_task() -> str:
        started.set()
        release.wait(timeout=2)
        return "done"

    task = executor.issue_task(blocking_task, name="block", project="proj", session_id="sess-1")
    assert started.wait(timeout=1), "Task did not start"
    infos = executor.get_current_tasks()
    info = next(info for info in infos if info.task_id == task.task_id)
    assert info.project == "proj"
    assert info.session_id == "sess-1"
    assert info.is_running
    release.set()
    assert task.result() == "done"
