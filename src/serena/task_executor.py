import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar

import logging
from serena.util.logging import LogTime

from serena.util.logging import log_context
from serena.util.string_utils import ToStringMixin

log = logging.getLogger(__name__)
T = TypeVar("T")


class ReadWriteLock:
    """A simple reader-writer lock allowing concurrent reads and exclusive writes."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False

    def acquire_read(self) -> None:
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self) -> None:
        with self._cond:
            while self._writer or self._readers > 0:
                self._cond.wait()
            self._writer = True

    def release_write(self) -> None:
        with self._cond:
            self._writer = False
            self._cond.notify_all()


class TaskExecutor:
    _GLOBAL_KEY = "__global__"

    def __init__(self, name: str, max_workers: int | None = None):
        workers = max_workers or max(4, (os.cpu_count() or 2))
        self._name = name
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self._lock = threading.Lock()
        self._tasks: dict[int, TaskExecutor.Task] = {}
        self._project_locks: dict[str, ReadWriteLock] = {}
        self._task_index = 1
        self._last_executed_task_info: TaskExecutor.TaskInfo | None = None

    class Task(ToStringMixin, Generic[T]):
        def __init__(
            self,
            *,
            function: Callable[[], T],
            name: str,
            project_key: str,
            read_only: bool,
            logged: bool,
            timeout: float | None,
            session_id: str | None,
            task_id: int,
        ) -> None:
            self._function = function
            self.name = name
            self.project_key = project_key
            self.read_only = read_only
            self.logged = logged
            self.timeout = timeout
            self.session_id = session_id
            self.task_id = task_id
            self.future: Future[T] = Future()

        def _tostring_includes(self) -> list[str]:
            return ["name", "project_key", "read_only"]

        def is_done(self) -> bool:
            return self.future.done()

        def result(self, timeout: float | None = None) -> T:
            effective_timeout = timeout if timeout is not None else self.timeout
            return self.future.result(timeout=effective_timeout)

        def cancel(self) -> None:
            self.future.cancel()

        def wait_until_done(self, timeout: float | None = None) -> None:
            try:
                self.result(timeout=timeout)
            except Exception:
                pass

    @dataclass
    class TaskInfo:
        name: str
        is_running: bool
        future: Future
        task_id: int
        logged: bool
        project: str
        read_only: bool
        session_id: str | None

        def finished_successfully(self) -> bool:
            return self.future.done() and not self.future.cancelled() and self.future.exception() is None

        @staticmethod
        def from_task(task: "TaskExecutor.Task", is_running: bool) -> "TaskExecutor.TaskInfo":
            return TaskExecutor.TaskInfo(
                name=task.name,
                is_running=is_running,
                future=task.future,
                task_id=task.task_id,
                logged=task.logged,
                project=task.project_key,
                read_only=task.read_only,
                session_id=task.session_id,
            )

        def cancel(self) -> None:
            self.future.cancel()

    def _get_lock(self, project_key: str) -> ReadWriteLock:
        with self._lock:
            lock = self._project_locks.get(project_key)
            if lock is None:
                lock = ReadWriteLock()
                self._project_locks[project_key] = lock
            return lock

    def get_current_tasks(self) -> list[TaskInfo]:
        tasks: list[TaskExecutor.TaskInfo] = []
        with self._lock:
            for task in self._tasks.values():
                if task.future.done():
                    continue
                tasks.append(self.TaskInfo.from_task(task, is_running=task.future.running()))
        return tasks

    def issue_task(
        self,
        task: Callable[[], T],
        *,
        name: str | None = None,
        logged: bool = True,
        timeout: float | None = None,
        project: str | None = None,
        read_only: bool = False,
        session_id: str | None = None,
    ) -> "TaskExecutor.Task[T]":
        with self._lock:
            task_number = self._task_index
            self._task_index += 1
        task_prefix_name = f"Task-{task_number}" if logged else "BackgroundTask"
        task_name = f"{task_prefix_name}:{name or task.__name__}"
        if logged:
            log.info(
                "Scheduling %s (project=%s, read_only=%s, session=%s)",
                task_name,
                project or "global",
                read_only,
                session_id,
            )

        project_key = project or self._GLOBAL_KEY
        task_obj = self.Task(
            function=task,
            name=task_name,
            project_key=project_key,
            read_only=read_only,
            logged=logged,
            timeout=timeout,
            session_id=session_id,
            task_id=task_number,
        )

        with self._lock:
            self._tasks[task_obj.task_id] = task_obj

        def runner() -> T:
            context_project = None if project_key == self._GLOBAL_KEY else project
            with log_context(session_id, context_project):
                lock = self._get_lock(project_key)
                if read_only:
                    lock.acquire_read()
                else:
                    lock.acquire_write()
                try:
                    if task_obj.logged:
                        log.info(
                            "Starting execution of %s (project=%s, read_only=%s, session=%s)",
                            task_obj.name,
                            project or "global",
                            read_only,
                            session_id,
                        )
                    with LogTime(task_obj.name, logger=log, enabled=task_obj.logged):
                        return task()
                except Exception as exc:
                    log.error(f"Error during execution of {task_obj.name}: {exc}", exc_info=exc)
                    raise
                finally:
                    if read_only:
                        lock.release_read()
                    else:
                        lock.release_write()

        future = self._executor.submit(runner)
        task_obj.future = future

        def _on_complete(fut: Future) -> None:
            with self._lock:
                existing = self._tasks.pop(task_obj.task_id, None)
                if existing is not None:
                    self._last_executed_task_info = self.TaskInfo.from_task(existing, is_running=False)
            if task_obj.logged and not fut.cancelled():
                log.info("Completed %s", task_obj.name)

        future.add_done_callback(_on_complete)
        return task_obj

    def execute_task(
        self,
        task: Callable[[], T],
        *,
        name: str | None = None,
        logged: bool = True,
        timeout: float | None = None,
        project: str | None = None,
        read_only: bool = False,
        session_id: str | None = None,
    ) -> T:
        task_obj = self.issue_task(
            task,
            name=name,
            logged=logged,
            timeout=timeout,
            project=project,
            read_only=read_only,
            session_id=session_id,
        )
        return task_obj.result()

    def get_last_executed_task(self) -> TaskInfo | None:
        with self._lock:
            return self._last_executed_task_info

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
