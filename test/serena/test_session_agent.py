"""
Tests for SerenaAgent session-related functionality.

Covers:
- Session manager integration
- Session project resolution (resolve_session_project, get_session_project)
- Idle project tracking with session touching
- get_session_manager accessor
"""

import time
from pathlib import Path

import pytest

from serena.agent import SerenaAgent
from serena.config.serena_config import ProjectConfig, RegisteredProject, SerenaConfig
from serena.project import Project
from serena.session_manager import SessionManager
from solidlsp.ls_config import Language


@pytest.fixture
def serena_config(tmp_path):
    """Create a minimal SerenaConfig with a test project."""
    config = SerenaConfig(gui_log_window=False, web_dashboard=False)

    # Create a minimal test project directory
    project_root = str(tmp_path / "test_project")
    Path(project_root).mkdir(exist_ok=True)
    (Path(project_root) / ".serena").mkdir(exist_ok=True)

    project_config = ProjectConfig(
        project_name="test_project",
        languages=[Language.PYTHON],
        ignored_paths=[],
        excluded_tools=[],
        read_only=False,
        ignore_all_files_in_gitignore=True,
        initial_prompt="",
        encoding="utf-8",
    )

    project = Project(
        project_root=project_root,
        project_config=project_config,
        serena_config=config,
    )
    config.projects = [RegisteredProject.from_project_instance(project)]
    return config


@pytest.fixture
def serena_agent(serena_config):
    """Create a SerenaAgent with the test config."""
    agent = SerenaAgent(serena_config=serena_config)
    yield agent
    agent.on_shutdown(timeout=5)


@pytest.fixture
def serena_agent_with_project(serena_config):
    """Create a SerenaAgent with the test project already activated."""
    project = serena_config.projects[0].get_project_instance(serena_config)
    agent = SerenaAgent(project=project.project_name, serena_config=serena_config)
    yield agent
    agent.on_shutdown(timeout=5)


class TestSessionManagerIntegration:
    """Tests for SerenaAgent's session manager integration."""

    def test_agent_has_session_manager(self, serena_agent):
        """Agent should have a SessionManager instance."""
        sm = serena_agent.get_session_manager()
        assert isinstance(sm, SessionManager)

    def test_get_session_manager_returns_same_instance(self, serena_agent):
        """Multiple calls should return the same SessionManager."""
        sm1 = serena_agent.get_session_manager()
        sm2 = serena_agent.get_session_manager()
        assert sm1 is sm2

    def test_session_manager_initially_empty(self, serena_agent):
        """Fresh agent should have no sessions."""
        sm = serena_agent.get_session_manager()
        assert sm.get_active_session_count() == 0
        assert sm.get_all_sessions() == []


class TestResolveSessionProject:
    """Tests for SerenaAgent.resolve_session_project()."""

    def test_resolve_with_valid_cwd(self, serena_agent_with_project, serena_config):
        """Should resolve project from cwd via longest-prefix matching."""
        project = serena_config.projects[0].get_project_instance(serena_config)
        cwd = project.project_root
        result = serena_agent_with_project.resolve_session_project("sess-1", cwd)
        assert result is not None
        assert result.project_name == "test_project"

    def test_resolve_with_cwd_caches_for_session(self, serena_agent_with_project, serena_config):
        """Resolution from cwd should cache the project for the session."""
        project = serena_config.projects[0].get_project_instance(serena_config)
        cwd = project.project_root

        serena_agent_with_project.resolve_session_project("sess-1", cwd)

        # Check session manager has the binding
        sm = serena_agent_with_project.get_session_manager()
        assert sm.get_project_name("sess-1") == "test_project"

        # Check session cache
        assert serena_agent_with_project._session_projects.get("sess-1") == "test_project"

    def test_resolve_falls_back_to_session_manager(self, serena_agent_with_project):
        """Should fall back to session manager's project binding when cwd is None."""
        # Pre-bind the session to a project
        sm = serena_agent_with_project.get_session_manager()
        sm.set_project("sess-1", "test_project")

        result = serena_agent_with_project.resolve_session_project("sess-1", None)
        assert result is not None
        assert result.project_name == "test_project"

    def test_resolve_falls_back_to_session_cache(self, serena_agent_with_project):
        """Should fall back to session-cached project name."""
        # Set the session cache directly (simulating a prior resolution)
        serena_agent_with_project._session_projects["sess-1"] = "test_project"

        result = serena_agent_with_project.resolve_session_project("sess-1", None)
        # Should return the project via fallback to get_active_project()
        assert result is not None

    def test_resolve_falls_back_to_first_active_project(self, serena_agent_with_project):
        """Should fall back to first active project when no session info."""
        result = serena_agent_with_project.resolve_session_project(None, None)
        assert result is not None
        assert result.project_name == "test_project"

    def test_resolve_with_none_session_id(self, serena_agent_with_project):
        """Should work when session_id is None (backward compat)."""
        result = serena_agent_with_project.resolve_session_project(None, None)
        assert result is not None

    def test_resolve_session_project_cwd_takes_precedence_over_session_binding(
        self, serena_agent_with_project, serena_config
    ):
        """CWD resolution should override session manager binding."""
        # Bind session to a different project name (won't resolve)
        sm = serena_agent_with_project.get_session_manager()
        sm.set_project("sess-1", "nonexistent_project")

        project = serena_config.projects[0].get_project_instance(serena_config)
        cwd = project.project_root

        result = serena_agent_with_project.resolve_session_project("sess-1", cwd)
        assert result is not None
        assert result.project_name == "test_project"
        # Session should now be rebound to the resolved project
        assert sm.get_project_name("sess-1") == "test_project"


class TestGetSessionProject:
    """Tests for SerenaAgent.get_session_project()."""

    def test_get_session_project_from_manager(self, serena_agent_with_project):
        """Should return project from session manager binding."""
        # Bind session
        sm = serena_agent_with_project.get_session_manager()
        sm.set_project("sess-1", "test_project")

        result = serena_agent_with_project.get_session_project("sess-1")
        assert result is not None
        assert result.project_name == "test_project"

    def test_get_session_project_returns_none_for_unbound(self, serena_agent):
        """Should return None for session with no project binding."""
        result = serena_agent.get_session_project("sess-unknown")
        assert result is None


class TestIdleProjectTracking:
    """Tests for idle project tracking with session touching."""

    def test_touch_project_updates_timestamp(self, serena_agent_with_project, serena_config):
        """Touching a project should update its last-active timestamp."""
        project = serena_config.projects[0].get_project_instance(serena_config)

        old_ts = serena_agent_with_project._project_last_active.get("test_project", 0)
        time.sleep(0.01)
        serena_agent_with_project._touch_project(project)
        new_ts = serena_agent_with_project._project_last_active.get("test_project", 0)
        assert new_ts > old_ts

    def test_touch_project_touches_bound_sessions(self, serena_agent_with_project, serena_config):
        """Touching a project should also touch all sessions bound to it."""
        project = serena_config.projects[0].get_project_instance(serena_config)

        # Register sessions bound to this project
        sm = serena_agent_with_project.get_session_manager()
        sm.register_session("sess-1", project_name="test_project")
        sm.register_session("sess-2", project_name="test_project")

        # Get old timestamps
        sess1 = sm.get_session("sess-1")
        sess2 = sm.get_session("sess-2")
        old_ts1 = sess1.last_active_at
        old_ts2 = sess2.last_active_at

        time.sleep(0.01)
        serena_agent_with_project._touch_project(project)

        # Sessions should have been touched
        sess1 = sm.get_session("sess-1")
        sess2 = sm.get_session("sess-2")
        assert sess1.last_active_at > old_ts1
        assert sess2.last_active_at > old_ts2

    def test_touch_project_does_not_touch_unrelated_sessions(self, serena_agent_with_project, serena_config):
        """Touching a project should not touch sessions bound to other projects."""
        project = serena_config.projects[0].get_project_instance(serena_config)

        sm = serena_agent_with_project.get_session_manager()
        sm.register_session("sess-1", project_name="test_project")
        sm.register_session("sess-2", project_name="other_project")

        sess1 = sm.get_session("sess-1")
        sess2 = sm.get_session("sess-2")
        old_ts1 = sess1.last_active_at
        old_ts2 = sess2.last_active_at

        time.sleep(0.01)
        serena_agent_with_project._touch_project(project)

        # sess-1 should be touched
        sess1 = sm.get_session("sess-1")
        assert sess1.last_active_at > old_ts1

        # sess-2 should NOT be touched (different project)
        sess2 = sm.get_session("sess-2")
        assert sess2.last_active_at == old_ts2

    def test_idle_checker_starts(self, serena_agent):
        """Idle checker timer should be started."""
        assert serena_agent._idle_timer is not None
        assert serena_agent._idle_timer.is_alive() or not serena_agent._idle_timer.finished.is_set()

    def test_check_idle_projects_no_crash_on_empty(self, serena_agent):
        """Idle checker should handle empty project list gracefully."""
        # Should not raise
        serena_agent._check_idle_projects()

    def test_idle_checker_keeps_project_with_active_sessions(self, serena_agent_with_project):
        agent = serena_agent_with_project
        agent.serena_config.project_idle_timeout_seconds = 0
        agent._project_last_active["test_project"] = time.time() - 1
        agent.get_session_manager().register_session("sess-keep", project_name="test_project")

        agent._check_idle_projects()

        assert "test_project" in agent._active_projects

    def test_idle_checker_shuts_down_when_no_sessions(self, serena_agent_with_project):
        agent = serena_agent_with_project
        agent.serena_config.project_idle_timeout_seconds = 0
        agent._project_last_active["test_project"] = time.time() - 1

        agent._check_idle_projects()

        assert "test_project" not in agent._active_projects


class TestInitializeSession:
    """Tests for SerenaAgent.initialize_session handshake behavior."""

    def test_initialize_session_binds_existing_project(self, serena_agent_with_project):
        agent = serena_agent_with_project

        state = agent.initialize_session(
            "session-1",
            project="test_project",
            context="agent",
            client_info="test-client 1.0",
        )

        assert state.project_name == "test_project"
        assert state.client_info == "test-client 1.0"
        manager = agent.get_session_manager()
        assert manager.get_project_name("session-1") == "test_project"

    def test_initialize_session_requires_auto_register_flag(self, serena_config, tmp_path):
        new_project_dir = tmp_path / "new_project"
        new_project_dir.mkdir()

        agent = SerenaAgent(serena_config=serena_config, auto_register_projects=False)
        try:
            with pytest.raises(ValueError):
                agent.initialize_session("sess-new", project=str(new_project_dir))

            # Project should remain unregistered
            assert serena_config.get_project(str(new_project_dir)) is None
        finally:
            agent.on_shutdown(timeout=5)

    def test_initialize_session_auto_registers_when_enabled(self, serena_config, tmp_path):
        new_project_dir = tmp_path / "auto_project"
        new_project_dir.mkdir()

        agent = SerenaAgent(serena_config=serena_config, auto_register_projects=True)
        try:
            state = agent.initialize_session("sess-auto", project=str(new_project_dir))
            assert state.project_name is not None
            # Project should now be registered and active
            registered = agent.serena_config.get_project(str(new_project_dir))
            assert registered is not None
            assert state.project_name == registered.project_name
            assert agent.get_session_manager().get_project_name("sess-auto") == registered.project_name
        finally:
            agent.on_shutdown(timeout=5)
