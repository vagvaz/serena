"""
Tests for the SessionManager and SessionState classes.

Covers the implemented session management infrastructure for multi-client daemon mode.
"""

import time
from unittest.mock import patch

import pytest

from serena.session_manager import SessionManager, SessionState


class TestSessionState:
    """Tests for the SessionState dataclass."""

    def test_default_values(self):
        state = SessionState(session_id="test-session-1")
        assert state.session_id == "test-session-1"
        assert state.project_name is None
        assert state.context_name is None
        assert state.client_info is None
        assert state.is_active is True
        assert isinstance(state.created_at, float)
        assert isinstance(state.last_active_at, float)

    def test_to_dict(self):
        state = SessionState(
            session_id="sess-1",
            project_name="my-project",
            context_name="dev",
            client_info="opencode 1.0.0",
        )
        d = state.to_dict()
        assert d["session_id"] == "sess-1"
        assert d["project_name"] == "my-project"
        assert d["context_name"] == "dev"
        assert d["client_info"] == "opencode 1.0.0"
        assert d["is_active"] is True
        assert "idle_seconds" in d
        assert isinstance(d["idle_seconds"], (int, float))
        assert d["idle_seconds"] >= 0

    def test_touch_updates_last_active(self):
        state = SessionState(session_id="sess-1")
        old_ts = state.last_active_at
        time.sleep(0.01)
        state.touch()
        assert state.last_active_at > old_ts

    def test_idle_seconds_increases(self):
        state = SessionState(session_id="sess-1")
        idle_1 = state.to_dict()["idle_seconds"]
        time.sleep(0.05)
        idle_2 = state.to_dict()["idle_seconds"]
        assert idle_2 > idle_1


class TestSessionManager:
    """Tests for the SessionManager class."""

    @pytest.fixture
    def manager(self):
        return SessionManager()

    # ── Registration ──────────────────────────────────────────────────────

    def test_register_new_session(self, manager):
        state = manager.register_session("sess-1", client_info="opencode 1.0.0")
        assert state.session_id == "sess-1"
        assert state.client_info == "opencode 1.0.0"
        assert state.is_active is True
        assert state.project_name is None

    def test_register_with_project_and_context(self, manager):
        state = manager.register_session(
            "sess-1",
            client_info="vscode",
            project_name="project-a",
            context_name="debug",
        )
        assert state.project_name == "project-a"
        assert state.context_name == "debug"
        assert state.client_info == "vscode"

    def test_register_existing_session_updates(self, manager):
        manager.register_session("sess-1", client_info="old-client")
        state = manager.register_session("sess-1", client_info="new-client", project_name="proj-x")
        assert state.client_info == "new-client"
        assert state.project_name == "proj-x"
        assert state.is_active is True

    def test_register_existing_session_preserves_unset_fields(self, manager):
        manager.register_session("sess-1", client_info="client-a", project_name="proj-a")
        # Update only client_info; project_name should remain
        state = manager.register_session("sess-1", client_info="client-b")
        assert state.client_info == "client-b"
        assert state.project_name == "proj-a"

    # ── Unregistration ────────────────────────────────────────────────────

    def test_unregister_session(self, manager):
        manager.register_session("sess-1")
        manager.unregister_session("sess-1")
        state = manager.get_session("sess-1")
        assert state is not None
        assert state.is_active is False

    def test_unregister_nonexistent_session(self, manager):
        # Should not raise
        manager.unregister_session("nonexistent")

    # ── Getters ───────────────────────────────────────────────────────────

    def test_get_session_returns_state(self, manager):
        manager.register_session("sess-1", client_info="test")
        state = manager.get_session("sess-1")
        assert state is not None
        assert state.session_id == "sess-1"
        assert state.client_info == "test"

    def test_get_session_returns_none_for_unknown(self, manager):
        assert manager.get_session("unknown") is None

    def test_get_project_name(self, manager):
        manager.register_session("sess-1", project_name="proj-a")
        assert manager.get_project_name("sess-1") == "proj-a"
        assert manager.get_project_name("unknown") is None

    # ── Set project ───────────────────────────────────────────────────────

    def test_set_project_on_existing_session(self, manager):
        manager.register_session("sess-1")
        manager.set_project("sess-1", "proj-b")
        assert manager.get_project_name("sess-1") == "proj-b"

    def test_set_project_creates_session_if_missing(self, manager):
        manager.set_project("sess-new", "proj-c")
        state = manager.get_session("sess-new")
        assert state is not None
        assert state.project_name == "proj-c"
        assert state.session_id == "sess-new"

    def test_set_project_touches_session(self, manager):
        manager.register_session("sess-1")
        state = manager.get_session("sess-1")
        old_ts = state.last_active_at
        time.sleep(0.01)
        manager.set_project("sess-1", "proj-x")
        state = manager.get_session("sess-1")
        assert state.last_active_at > old_ts

    # ── Active sessions ───────────────────────────────────────────────────

    def test_get_active_sessions(self, manager):
        manager.register_session("sess-1", project_name="proj-a")
        manager.register_session("sess-2", project_name="proj-b")
        manager.unregister_session("sess-1")

        active = manager.get_active_sessions()
        assert len(active) == 1
        assert active[0].session_id == "sess-2"

    def test_get_all_sessions(self, manager):
        manager.register_session("sess-1")
        manager.register_session("sess-2")
        manager.unregister_session("sess-1")

        all_sessions = manager.get_all_sessions()
        assert len(all_sessions) == 2

    # ── Sessions for project ──────────────────────────────────────────────

    def test_get_sessions_for_project(self, manager):
        manager.register_session("sess-1", project_name="proj-a")
        manager.register_session("sess-2", project_name="proj-a")
        manager.register_session("sess-3", project_name="proj-b")

        proj_a_sessions = manager.get_sessions_for_project("proj-a")
        assert len(proj_a_sessions) == 2
        ids = {s.session_id for s in proj_a_sessions}
        assert ids == {"sess-1", "sess-2"}

    def test_get_sessions_for_project_excludes_inactive(self, manager):
        manager.register_session("sess-1", project_name="proj-a")
        manager.register_session("sess-2", project_name="proj-a")
        manager.unregister_session("sess-1")

        proj_a_sessions = manager.get_sessions_for_project("proj-a")
        assert len(proj_a_sessions) == 1
        assert proj_a_sessions[0].session_id == "sess-2"

    # ── Counts ────────────────────────────────────────────────────────────

    def test_get_active_session_count(self, manager):
        manager.register_session("sess-1")
        manager.register_session("sess-2")
        manager.unregister_session("sess-1")
        assert manager.get_active_session_count() == 1

    def test_get_project_session_count(self, manager):
        manager.register_session("sess-1", project_name="proj-a")
        manager.register_session("sess-2", project_name="proj-a")
        manager.register_session("sess-3", project_name="proj-b")
        assert manager.get_project_session_count("proj-a") == 2
        assert manager.get_project_session_count("proj-b") == 1
        assert manager.get_project_session_count("proj-c") == 0

    # ── Serialization ─────────────────────────────────────────────────────

    def test_to_dict_list(self, manager):
        manager.register_session("sess-1", project_name="proj-a", client_info="client-1")
        manager.register_session("sess-2", project_name="proj-b", client_info="client-2")
        result = manager.to_dict_list()
        assert len(result) == 2
        # Each entry should have all expected keys
        for entry in result:
            assert "session_id" in entry
            assert "project_name" in entry
            assert "client_info" in entry
            assert "idle_seconds" in entry
            assert "is_active" in entry

    # ── Thread safety ─────────────────────────────────────────────────────

    def test_concurrent_registration(self, manager):
        """Multiple threads registering sessions should not corrupt state."""
        import threading

        errors = []

        def register(i):
            try:
                manager.register_session(f"sess-{i}", project_name=f"proj-{i % 3}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent registration: {errors}"
        assert manager.get_active_session_count() == 50

    def test_concurrent_read_write(self, manager):
        """Concurrent reads and writes should not raise."""
        import threading

        manager.register_session("sess-1", project_name="proj-a")
        errors = []

        def writer():
            try:
                for i in range(100):
                    manager.set_project("sess-1", f"proj-{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    manager.get_project_name("sess-1")
                    manager.get_active_session_count()
                    manager.to_dict_list()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Errors during concurrent read/write: {errors}"
