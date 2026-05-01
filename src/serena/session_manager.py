"""
Session management for multi-client daemon mode.

Each MCP client connection gets a SessionState that tracks:
- The project associated with this session
- The context/persona for this session
- Last activity timestamp
- Client metadata (name, version)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import logging

log = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Mutable state for a single MCP client session."""

    session_id: str
    """Unique MCP session identifier."""

    project_name: str | None = None
    """The project this session is bound to (None until activated)."""

    context_name: str | None = None
    """Optional per-session context override."""

    persona_name: str | None = None
    """Optional per-session persona override."""

    tool_allowlist: tuple[str, ...] | None = None
    """Optional per-session allowlist of tool names."""

    backend_hint: str | None = None
    """Optional hint about the preferred backend (e.g., 'lsp', 'jetbrains')."""

    client_info: str | None = None
    """Human-readable client string, e.g. 'opencode 1.0.0'."""

    created_at: float = field(default_factory=time.time)
    """Timestamp when the session was registered."""

    last_active_at: float = field(default_factory=time.time)
    """Timestamp of the last tool call from this session."""

    is_active: bool = True
    """Whether the session is still connected."""

    def touch(self) -> None:
        """Update the last-active timestamp."""
        self.last_active_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize for dashboard/API consumption."""
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "context_name": self.context_name,
            "persona_name": self.persona_name,
            "tool_allowlist": list(self.tool_allowlist) if self.tool_allowlist is not None else None,
            "backend_hint": self.backend_hint,
            "client_info": self.client_info,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "is_active": self.is_active,
            "idle_seconds": time.time() - self.last_active_at,
        }


class SessionManager:
    """Thread-safe registry of active MCP sessions.

    Provides per-session state tracking for the multi-client daemon use case.
    Each session is keyed by its MCP session ID and maintains its own project
    binding, context, and activity timestamps.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def register_session(
        self,
        session_id: str,
        *,
        client_info: str | None = None,
        project_name: str | None = None,
        context_name: str | None = None,
        persona_name: str | None = None,
        tool_allowlist: Sequence[str] | None = None,
        backend_hint: str | None = None,
    ) -> SessionState:
        """Register or update a session.

        If the session already exists, updates its metadata and marks it active.
        """
        allowlist_tuple = tuple(dict.fromkeys(tool_allowlist)) if tool_allowlist is not None else None
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState(
                    session_id=session_id,
                    client_info=client_info,
                    project_name=project_name,
                    context_name=context_name,
                    persona_name=persona_name,
                    tool_allowlist=allowlist_tuple,
                    backend_hint=backend_hint,
                )
                self._sessions[session_id] = state
                log.info(
                    "Registered new session %s (client=%s, project=%s, context=%s, persona=%s)",
                    session_id,
                    client_info,
                    project_name,
                    context_name,
                    persona_name,
                )
            else:
                state.is_active = True
                state.touch()
                if client_info is not None:
                    state.client_info = client_info
                if project_name is not None:
                    state.project_name = project_name
                if context_name is not None:
                    state.context_name = context_name
                if persona_name is not None:
                    state.persona_name = persona_name
                if allowlist_tuple is not None:
                    state.tool_allowlist = allowlist_tuple
                if backend_hint is not None:
                    state.backend_hint = backend_hint
                log.debug("Updated session %s", session_id)
            return state

    def update_session(
        self,
        session_id: str,
        *,
        client_info: str | None = None,
        project_name: str | None = None,
        context_name: str | None = None,
        persona_name: str | None = None,
        tool_allowlist: Sequence[str] | None = None,
        backend_hint: str | None = None,
        is_active: bool | None = True,
    ) -> SessionState:
        """Update fields on a session, creating it if necessary."""
        allowlist_tuple = tuple(dict.fromkeys(tool_allowlist)) if tool_allowlist is not None else None
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState(session_id=session_id)
                self._sessions[session_id] = state
            if client_info is not None:
                state.client_info = client_info
            if project_name is not None:
                state.project_name = project_name
            if context_name is not None:
                state.context_name = context_name
            if persona_name is not None:
                state.persona_name = persona_name
            if allowlist_tuple is not None:
                state.tool_allowlist = allowlist_tuple
            if backend_hint is not None:
                state.backend_hint = backend_hint
            if is_active is not None:
                state.is_active = is_active
            state.touch()
            log.debug(
                "Session %s updated (project=%s, context=%s, persona=%s, allowlist=%s, backend_hint=%s)",
                session_id,
                state.project_name,
                state.context_name,
                state.persona_name,
                state.tool_allowlist,
                state.backend_hint,
            )
            return state

    def unregister_session(self, session_id: str) -> None:
        """Mark a session as inactive (client disconnected)."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].is_active = False
                log.info(f"Unregistered session {session_id}")

    def get_session(self, session_id: str) -> SessionState | None:
        """Get session state, or None if not registered."""
        with self._lock:
            return self._sessions.get(session_id)

    def get_project_name(self, session_id: str) -> str | None:
        """Get the project bound to a session, or None."""
        with self._lock:
            state = self._sessions.get(session_id)
            return state.project_name if state else None

    def set_project(self, session_id: str, project_name: str) -> None:
        """Bind a session to a project."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState(session_id=session_id, project_name=project_name)
                self._sessions[session_id] = state
            else:
                state.project_name = project_name
                state.touch()
            log.debug(f"Session {session_id} bound to project {project_name}")

    def get_active_sessions(self) -> list[SessionState]:
        """Return a snapshot of all active sessions."""
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active]

    def get_all_sessions(self) -> list[SessionState]:
        """Return a snapshot of all sessions (active and inactive)."""
        with self._lock:
            return list(self._sessions.values())

    def get_sessions_for_project(self, project_name: str) -> list[SessionState]:
        """Return sessions bound to a specific project."""
        with self._lock:
            return [s for s in self._sessions.values() if s.project_name == project_name and s.is_active]

    def get_active_session_count(self) -> int:
        """Number of currently active sessions."""
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.is_active)

    def get_project_session_count(self, project_name: str) -> int:
        """Number of active sessions bound to a project."""
        with self._lock:
            return sum(
                1 for s in self._sessions.values()
                if s.project_name == project_name and s.is_active
            )

    def to_dict_list(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Serialize sessions for API/dashboard consumption.

        :param active_only: If True (default), only return active sessions.
        """
        with self._lock:
            sessions = self._sessions.values()
            if active_only:
                sessions = [s for s in sessions if s.is_active]
            return [s.to_dict() for s in sessions]
