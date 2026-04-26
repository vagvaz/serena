"""
Project management for multi-project Serena agents.

Owns the lifecycle of N active projects. Every project must be resolved
explicitly by name, path, or session binding. There is NO ambiguous
"get active project" — callers that cannot determine which project they
need get ``None`` and must error, not guess.

The thread-local ``_current_project`` (set by ``project_context()`` in
``tools_base``) is the mechanism for project-aware tool execution.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from sensai.util.logging import LogTime

from serena.config.serena_config import LanguageBackend, SerenaConfig
from serena.session_manager import SessionManager
from serena.task_executor import TaskExecutor

if TYPE_CHECKING:
    from serena.project import Project

log = logging.getLogger(__name__)


class ProjectManager:
    """
    Manages zero or more active projects.

    Responsibilities:
    * Maintain the set of active projects.
    * Resolve which project a tool call refers to (by path, session, or name).
    * Start/stop language servers for projects in LSP mode.
    * Track project activity for idle timeout.
    * Persist/restore project state to/from disk.

    There is **no** ambiguous ``get_active_project()`` — see
    :meth:`get_by_name`, :meth:`resolve_for_path`, and
    :meth:`resolve_for_session` instead.
    """

    def __init__(
        self,
        serena_config: SerenaConfig,
        session_manager: SessionManager,
        task_executor: TaskExecutor,
        language_backend: LanguageBackend,
        on_projects_changed: Callable[[], None] | None = None,
    ) -> None:
        """
        :param serena_config: global Serena configuration (provides idle config,
            project enumeration for restore, etc.)
        :param session_manager: session state registry (session-project bindings
            are managed here, not duplicated in ProjectManager)
        :param task_executor: executor for async language server startup
        :param language_backend: the effective language backend for this session
        :param on_projects_changed: optional callback fired after any project is
            added or removed; the caller (SerenaAgent) typically updates modes
            and tools in response
        """
        self._active_projects: dict[str, Project] = {}
        """project_name → Project instance for all currently active projects."""

        self._project_last_active: dict[str, float] = {}
        """project_name → timestamp of the last tool call on that project."""

        self._idle_timer: threading.Timer | None = None
        """Periodic timer for checking and shutting down idle projects."""

        self._serena_config = serena_config
        self._session_manager = session_manager
        self._task_executor = task_executor
        self._language_backend = language_backend
        self._on_projects_changed = on_projects_changed

    # ── Query ──────────────────────────────────────────────────────────────

    def get_by_name(self, name: str) -> Project | None:
        """
        Look up an active project by its canonical name.

        :param name: the project name
        :returns: the Project instance, or ``None`` if not active
        """
        return self._active_projects.get(name)

    def get_all(self) -> dict[str, Project]:
        """
        Return a snapshot of all active projects.

        :returns: ``{project_name: Project}``
        """
        return dict(self._active_projects)

    def count(self) -> int:
        """Return the number of currently active projects."""
        return len(self._active_projects)

    def is_active(self, name: str) -> bool:
        """Return whether a project with the given name is active."""
        return name in self._active_projects

    def get_last_active_timestamp(self, project_name: str) -> float | None:
        """
        Return the timestamp of the last tool call on the given project,
        or ``None`` if the project has never been touched.

        :param project_name: the canonical project name
        """
        return self._project_last_active.get(project_name)

    # ── Resolution ─────────────────────────────────────────────────────────

    def resolve_for_path(self, cwd: str) -> Project | None:
        """
        Find the active project whose root is a prefix of *cwd*.
        Uses longest-prefix matching to handle nested projects correctly.

        :param cwd: an absolute filesystem path
        :returns: the matching Project, or ``None``
        """
        cwd = os.path.normpath(cwd)

        # 1. Exact match first
        root_index = {p.project_root: p for p in self._active_projects.values()}
        if cwd in root_index:
            return root_index[cwd]

        # 2. Longest prefix match
        best_match: Project | None = None
        best_len = 0
        for root, project in root_index.items():
            if cwd.startswith(root) and len(root) > best_len:
                best_match = project
                best_len = len(root)
        return best_match

    def resolve_for_session(self, session_id: str | None, cwd: str | None) -> Project | None:
        """
        Resolve the active project for a tool call based on session binding
        and/or working directory.

        Resolution order:
        1. If *cwd* is provided, resolve via :meth:`resolve_for_path` and
           persist the binding in the session manager.
        2. Fall back to the session manager's project binding.
        3. Return ``None`` — the caller must error, not guess.

        :param session_id: MCP session/client identifier
        :param cwd: current working directory of the tool call
        :returns: a resolved Project, or ``None`` if ambiguous
        """
        # Step 1: resolve from cwd and cache for the session
        if cwd:
            project = self.resolve_for_path(cwd)
            if project and session_id:
                self._session_manager.set_project(session_id, project.project_name)
            return project

        # Step 2: fall back to session manager binding
        if session_id:
            manager_project_name = self._session_manager.get_project_name(session_id)
            if manager_project_name:
                project = self._active_projects.get(manager_project_name)
                if project:
                    return project

        # Step 3: ambiguous — caller must error
        return None

    def get_session_project(self, session_id: str) -> Project | None:
        """
        Get the project bound to a session (without resolving from cwd).

        :param session_id: MCP session/client identifier
        :returns: the Project, or ``None`` if unbound
        """
        manager_project_name = self._session_manager.get_project_name(session_id)
        if manager_project_name:
            return self._active_projects.get(manager_project_name)
        return None

    def resolve_project(
        self, project_root_or_name: str, serena_config: SerenaConfig
    ) -> Project | None:
        """
        Resolve a path or registered name to a *Project* instance,
        auto-registering the project if a directory path is given.

        .. note::
           The caller (SerenaAgent) is responsible for calling
           ``project.set_agent(agent)`` before passing the project to
           :meth:`add`.

        :param project_root_or_name: registered project name, or an
            absolute/relative path to a project directory
        :param serena_config: the Serena configuration for looking up
            registered projects
        :returns: a Project instance, or ``None`` if unresolvable
        """
        project = serena_config.get_project(project_root_or_name)
        if project is not None:
            return project
        if os.path.isdir(project_root_or_name):
            return serena_config.add_project_from_path(project_root_or_name)
        return None

    # ── Mutation ───────────────────────────────────────────────────────────

    def add(self, project: Project, *, notify: bool = True) -> bool:
        """
        Add a project to the active set.

        The caller must have already called ``project.set_agent(agent)``.

        :param project: a fully initialised Project instance
        :param notify: if ``True``, fire the ``on_projects_changed`` callback
        :returns: ``True`` if newly added, ``False`` if already active
        :raises ValueError: if the project's language backend differs from
            the backend initialised at startup
        """
        if project.project_name in self._active_projects:
            return False

        log.info("Adding %s at %s to active projects", project.project_name, project.project_root)

        # Validate backend compatibility
        project_backend = project.project_config.language_backend
        if project_backend is not None and project_backend != self._language_backend:
            raise ValueError(
                f"Cannot activate project '{project.project_name}': it requires "
                f"the {project_backend.value} backend, but this session was "
                f"initialised with {self._language_backend.value}. "
                f"Workarounds: (1) Use project activation at startup via --project, "
                f"(2) Configure one MCP server per backend in your client."
            )

        self._active_projects[project.project_name] = project

        # Initialise the language server in the background (LSP mode only)
        if self._language_backend.is_lsp():

            def _init_ls() -> None:
                with LogTime("Language server initialization", logger=log):
                    project.create_language_server_manager()

            self._task_executor.issue_task(_init_ls)

        if notify and self._on_projects_changed is not None:
            self._on_projects_changed()

        return True

    def remove(self, project_name: str, *, notify: bool = True) -> bool:
        """
        Remove a project from the active set and shut down its resources.

        :param project_name: the canonical project name
        :param notify: if ``True``, fire the ``on_projects_changed`` callback
        :returns: ``True`` if removed, ``False`` if not active
        """
        project = self._active_projects.pop(project_name, None)
        if project is None:
            return False

        log.info("Removing %s from active projects", project_name)
        project.shutdown()

        # Clean up session manager bindings for this project
        for session in self._session_manager.get_sessions_for_project(project_name):
            session.project_name = None

        if notify and self._on_projects_changed is not None:
            self._on_projects_changed()

        return True

    # ── Idle timeout ───────────────────────────────────────────────────────

    def touch(self, project: Project) -> None:
        """
        Update the last-active timestamp for a project and all sessions
        bound to it.

        Call this after each tool call on the given project.
        """
        self._project_last_active[project.project_name] = time.time()
        for session in self._session_manager.get_sessions_for_project(project.project_name):
            session.touch()

    def start_idle_checker(self, interval_seconds: float | None = None) -> None:
        """
        Start (or restart) the periodic background timer that checks for
        idle projects and shuts them down.

        :param interval_seconds: check interval; defaults to ``project_idle_check_interval_seconds``
            from the Serena configuration.
        """
        interval = interval_seconds or self._serena_config.project_idle_check_interval_seconds
        self._idle_timer = threading.Timer(interval, self._check_idle_projects)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _check_idle_projects(self) -> None:
        """Periodic check that shuts down projects idle past the timeout."""
        now = time.time()
        timeout = self._serena_config.project_idle_timeout_seconds
        changed = False

        for name, last_active in list(self._project_last_active.items()):
            session_count = self._session_manager.get_project_session_count(name)
            if session_count > 0:
                log.debug(
                    "Skipping idle shutdown for '%s' — %s session(s) remain bound",
                    name,
                    session_count,
                )
                continue

            idle_duration = now - last_active
            if idle_duration > timeout:
                project = self._active_projects.get(name)
                if project:
                    log.info(
                        "Project '%s' idle for %.0fs (timeout=%ss) — shutting down",
                        name,
                        idle_duration,
                        timeout,
                    )
                    self.persist(project)
                    self.remove(name, notify=False)
                    changed = True

        # Persist remaining projects' state periodically
        if not changed:
            for project in list(self._active_projects.values()):
                self.persist(project)

        # Reschedule
        self.start_idle_checker()

    # ── Persistence ────────────────────────────────────────────────────────

    def persist(self, project: Project) -> None:
        """
        Save a single project's active state to disk.

        The state is stored as ``<project.serena_folder>/active_state.json``
        and is read back by :meth:`restore_from_disk` on the next startup.
        """
        try:
            state_file = os.path.join(project.serena_folder, "active_state.json")
            ls_manager = project.language_server_manager
            state = {
                "project_name": project.project_name,
                "project_root": project.project_root,
                "last_active": self._project_last_active.get(project.project_name),
                "lsp_running": ls_manager.is_running() if ls_manager else False,
            }
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            with open(state_file, "w") as f:
                json.dump(state, f)
        except Exception as e:
            log.warning("Failed to persist state for '%s': %s", project.project_name, e)

    def persist_all(self) -> None:
        """Save state for every currently active project."""
        for project in list(self._active_projects.values()):
            self.persist(project)

    def restore_from_disk(self) -> None:
        """
        On agent startup, re-activate projects that were previously active
        (based on their saved ``active_state.json`` files).

        .. note::
           This method calls :meth:`add` with ``notify=False`` because mode
           and tool updates are handled once by the caller after restore.
           The caller must also call ``project.set_agent(agent)`` on each
           restored project first.
        """
        for registered in self._serena_config.projects:
            try:
                state_file = os.path.join(registered.project_root, ".serena", "active_state.json")
                if not os.path.exists(state_file):
                    continue
                with open(state_file) as f:
                    json.load(f)  # validate, but don't use values here
                project = registered.get_project_instance(self._serena_config)
                if project:
                    self.add(project, notify=False)
                    log.info("Restored project '%s' from disk state", project.project_name)
            except Exception as e:
                log.warning(
                    "Failed to restore project '%s' from disk: %s",
                    registered.project_name,
                    e,
                )

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def shutdown_all(self, timeout: float = 2.0) -> None:
        """
        Shut down every active project and cancel background timers.

        Calling this leaves the manager in an empty, usable state.
        """
        # Cancel the idle checker
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

        # Persist and shut down each project
        for name, project in list(self._active_projects.items()):
            log.info("Shutting down active project '%s' ...", name)
            project.shutdown(timeout=timeout)

        self._active_projects.clear()
        self._project_last_active.clear()
