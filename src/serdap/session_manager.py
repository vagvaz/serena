import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dap_client import DapClient
    from .multiplexer import Multiplexer

log = logging.getLogger(__name__)


class DebugSession:
    def __init__(self, project_name: str, multiplexer: "Multiplexer", dap_client: "DapClient | None" = None) -> None:
        self.project_name = project_name
        self.multiplexer = multiplexer
        self.dap_client = dap_client
        self._is_active = True

    def is_active(self) -> bool:
        return self._is_active

    def close(self) -> None:
        self._is_active = False
        if self.dap_client is not None:
            try:
                self.dap_client.close()
            except Exception:
                log.exception("Error closing DAP client for session %s", self.project_name)
            self.dap_client = None
        try:
            self.multiplexer.stop()
        except Exception:
            log.exception("Error stopping multiplexer for session %s", self.project_name)


class DebugSessionManager:
    _instance: "DebugSessionManager | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "DebugSessionManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = DebugSessionManager()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._shutdown_all()
                cls._instance = None

    def __init__(self) -> None:
        self._sessions: dict[str, DebugSession] = {}
        self._lock = threading.Lock()

    def create_session(
        self, project_name: str, multiplexer: "Multiplexer", dap_client: "DapClient | None" = None
    ) -> DebugSession:
        with self._lock:
            existing = self._sessions.get(project_name)
            if existing is not None and existing.is_active():
                existing.close()
            session = DebugSession(project_name, multiplexer, dap_client)
            self._sessions[project_name] = session
            log.info("Created debug session for project '%s'", project_name)
            return session

    def get_session(self, project_name: str) -> DebugSession | None:
        with self._lock:
            session = self._sessions.get(project_name)
            if session is not None and session.is_active():
                return session
            return None

    def close_session(self, project_name: str) -> None:
        with self._lock:
            session = self._sessions.pop(project_name, None)
            if session is not None:
                session.close()
                log.info("Closed debug session for project '%s'", project_name)

    def has_active_session(self, project_name: str) -> bool:
        return self.get_session(project_name) is not None

    def _shutdown_all(self) -> None:
        with self._lock:
            for project_name, session in list(self._sessions.items()):
                try:
                    session.close()
                except Exception:
                    log.exception("Error closing session for project '%s'", project_name)
            self._sessions.clear()
