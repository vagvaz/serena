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

        # Session cache was removed — only the session manager tracks bindings

    def test_resolve_falls_back_to_session_manager(self, serena_agent_with_project):
        """Should fall back to session manager's project binding when cwd is None."""
        # Pre-bind the session to a project
        sm = serena_agent_with_project.get_session_manager()
        sm.set_project("sess-1", "test_project")

        result = serena_agent_with_project.resolve_session_project("sess-1", None)
        assert result is not None
        assert result.project_name == "test_project"

    @pytest.mark.skip(reason="Session cache was removed in favor of SessionManager-only tracking")
    def test_resolve_falls_back_to_session_cache(self, serena_agent_with_project):
        """Should fall back to session-cached project name (removed — SessionManager only)."""

    def test_resolve_returns_none_when_no_session_info(self, serena_agent_with_project):
        """Should return None when no session info is available (no data bleeding)."""
        result = serena_agent_with_project.resolve_session_project(None, None)
        assert result is None

    def test_resolve_with_none_session_id(self, serena_agent_with_project):
        """Should return None when session_id is None and no cwd is provided."""
        result = serena_agent_with_project.resolve_session_project(None, None)
        assert result is None

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
        pm = serena_agent_with_project._project_manager

        old_ts = pm.get_last_active_timestamp("test_project") or 0
        time.sleep(0.01)
        serena_agent_with_project._touch_project(project)
        new_ts = pm.get_last_active_timestamp("test_project") or 0
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
        """Idle checker timer should be started on the ProjectManager."""
        assert serena_agent._project_manager._idle_timer is not None

    def test_idle_checker_keeps_project_with_active_sessions(self, serena_agent_with_project):
        agent = serena_agent_with_project
        pm = agent._project_manager
        agent.serena_config.project_idle_timeout_seconds = 0
        pm.touch(next(iter(pm.get_all().values())))
        import time as _time
        pm._project_last_active["test_project"] = _time.time() - 1
        agent.get_session_manager().register_session("sess-keep", project_name="test_project")

        pm._check_idle_projects()

        assert pm.is_active("test_project")

    def test_idle_checker_shuts_down_when_no_sessions(self, serena_agent_with_project):
        agent = serena_agent_with_project
        pm = agent._project_manager
        agent.serena_config.project_idle_timeout_seconds = 0
        pm._project_last_active["test_project"] = time.time() - 1

        pm._check_idle_projects()

        assert not pm.is_active("test_project")


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


class TestPersistProjectState:
    """Tests for SerenaAgent._persist_project_state() and _persist_all_projects()."""

    def test_persist_creates_active_state_file(self, serena_agent_with_project, serena_config):
        """Persist should create active_state.json in the project's .serena folder."""
        agent = serena_agent_with_project
        pm = agent._project_manager
        pm.touch(next(iter(pm.get_all().values())))
        pm.persist_all()

        project_root = serena_config.projects[0].get_project_instance(serena_config).project_root
        state_file = Path(project_root) / ".serena" / "active_state.json"
        assert state_file.exists(), "active_state.json should be created"

        import json

        with open(state_file) as f:
            state = json.load(f)

        assert state["project_name"] == "test_project"
        assert state["project_root"] == project_root
        assert "lsp_running" in state
        assert isinstance(state["lsp_running"], bool)

    def test_persist_handles_missing_ls_manager(self):
        """Persist should handle missing language server manager gracefully."""
        config = SerenaConfig(gui_log_window=False, web_dashboard=False)
        project_root = str(Path("/tmp/test_no_ls_project"))
        Path(project_root).mkdir(exist_ok=True)
        (Path(project_root) / ".serena").mkdir(exist_ok=True)

        project_config = ProjectConfig(
            project_name="test_no_ls",
            languages=[Language.PYTHON],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        )
        proj = Project(
            project_root=project_root,
            project_config=project_config,
            serena_config=config,
        )
        agent = SerenaAgent(serena_config=config)
        try:
            # This should not crash even though the project has no LSP manager yet
            agent._project_manager.persist(proj)
        except Exception:
            pytest.fail("Persist should handle missing LSP manager without crashing")
        finally:
            agent.on_shutdown(timeout=5)

    def test_persist_preserves_last_active(self):
        """Persist should preserve the last_active timestamp."""
        serena_config_for_persist = SerenaConfig(gui_log_window=False, web_dashboard=False)
        project_root = str(Path("/tmp/test_persist_timestamp"))
        Path(project_root).mkdir(exist_ok=True)
        (Path(project_root) / ".serena").mkdir(exist_ok=True)

        project_config = ProjectConfig(
            project_name="test_ts",
            languages=[Language.PYTHON],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        )
        proj = Project(
            project_root=project_root,
            project_config=project_config,
            serena_config=serena_config_for_persist,
        )
        serena_config_for_persist.projects = [RegisteredProject.from_project_instance(proj)]

        agent = SerenaAgent(project="test_ts", serena_config=serena_config_for_persist)
        try:
            pm = agent._project_manager
            expected_ts = time.time()
            pm._project_last_active["test_ts"] = expected_ts
            pm.persist_all()

            state_file = Path(project_root) / ".serena" / "active_state.json"
            import json

            with open(state_file) as f:
                state = json.load(f)

            assert abs(state["last_active"] - expected_ts) < 0.1
        finally:
            agent.on_shutdown(timeout=5)


class TestRestoreProjectsFromDisk:
    """Tests for SerenaAgent._restore_projects_from_disk()."""

    def test_restore_restores_active_project(self, serena_config, tmp_path):
        """Restored projects should be re-added to the active set."""
        project_root = str(tmp_path / "test_restore")
        Path(project_root).mkdir(exist_ok=True)
        (Path(project_root) / ".serena").mkdir(exist_ok=True)

        project_config = ProjectConfig(
            project_name="test_restore",
            languages=[Language.PYTHON],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        )
        proj = Project(
            project_root=project_root,
            project_config=project_config,
            serena_config=serena_config,
        )
        serena_config.projects = [RegisteredProject.from_project_instance(proj)]

        # First agent: activate and persist
        agent1 = SerenaAgent(project="test_restore", serena_config=serena_config)
        pm1 = agent1._project_manager
        assert pm1.is_active("test_restore")
        pm1.touch(next(iter(pm1.get_all().values())))
        pm1.persist_all()
        agent1.on_shutdown(timeout=5)

        # Fresh agent: restore (restore happens automatically in __init__,
        # but we test via project_manager directly)
        agent2 = SerenaAgent(serena_config=serena_config)
        pm2 = agent2._project_manager

        assert pm2.is_active("test_restore"), "Project should be restored via __init__"

    def test_restore_skips_missing_state_file(self, serena_config, tmp_path):
        """Restore should skip projects without an active_state.json file."""
        project_root = str(tmp_path / "test_no_state")
        Path(project_root).mkdir(exist_ok=True)
        (Path(project_root) / ".serena").mkdir(exist_ok=True)

        project_config = ProjectConfig(
            project_name="test_no_state",
            languages=[Language.PYTHON],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        )
        proj = Project(
            project_root=project_root,
            project_config=project_config,
            serena_config=serena_config,
        )
        serena_config.projects = [RegisteredProject.from_project_instance(proj)]

        agent = SerenaAgent(serena_config=serena_config)
        try:
            # No state file exists, so restore should skip
            agent._project_manager.restore_from_disk()
            assert not agent._project_manager.is_active("test_no_state")
        finally:
            agent.on_shutdown(timeout=5)

    def test_restore_skips_corrupted_state_file(self, serena_config, tmp_path):
        """Restore should skip corrupted/invalid state files gracefully."""
        project_root = str(tmp_path / "test_corrupted")
        Path(project_root).mkdir(exist_ok=True)
        serena_dir = Path(project_root) / ".serena"
        serena_dir.mkdir(exist_ok=True)

        # Write invalid JSON
        (serena_dir / "active_state.json").write_text("{broken json content")

        project_config = ProjectConfig(
            project_name="test_corrupted",
            languages=[Language.PYTHON],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        )
        proj = Project(
            project_root=project_root,
            project_config=project_config,
            serena_config=serena_config,
        )
        serena_config.projects = [RegisteredProject.from_project_instance(proj)]

        agent = SerenaAgent(serena_config=serena_config)
        try:
            agent._project_manager.restore_from_disk()
            assert not agent._project_manager.is_active("test_corrupted")
        finally:
            agent.on_shutdown(timeout=5)

    def test_restore_sets_agent_on_restored_project(self, serena_config, tmp_path):
        """Restored projects should have their agent reference set."""
        project_root = str(tmp_path / "test_restore_agent")
        Path(project_root).mkdir(exist_ok=True)
        (Path(project_root) / ".serena").mkdir(exist_ok=True)

        project_config = ProjectConfig(
            project_name="test_restore_agent",
            languages=[Language.PYTHON],
            ignored_paths=[],
            excluded_tools=[],
            read_only=False,
            ignore_all_files_in_gitignore=True,
            initial_prompt="",
            encoding="utf-8",
        )
        proj = Project(
            project_root=project_root,
            project_config=project_config,
            serena_config=serena_config,
        )
        serena_config.projects = [RegisteredProject.from_project_instance(proj)]

        agent1 = SerenaAgent(project="test_restore_agent", serena_config=serena_config)
        pm1 = agent1._project_manager
        pm1.touch(next(iter(pm1.get_all().values())))
        pm1.persist_all()
        agent1.on_shutdown(timeout=5)

        agent2 = SerenaAgent(serena_config=serena_config)
        pm2 = agent2._project_manager

        restored = pm2.get_by_name("test_restore_agent")
        assert restored is not None
        assert restored._agent is agent2, "Restored project should have agent reference set"
