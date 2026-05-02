from types import SimpleNamespace

from flask.testing import FlaskClient
from serena.dashboard import (
    DashboardPortFile,
    RequestLog,
    ResponseLog,
    ResponseToolNames,
    ResponseToolStats,
    SerenaDashboardAPI,
)
from serena.util.logging import LogEntry
from solidlsp.ls_config import Language


class _DummyMemoryLogHandler:
    def get_log_messages(self, from_idx: int = 0):  # pragma: no cover - simple stub
        return SimpleNamespace(messages=[], max_idx=-1)

    def clear_log_messages(self) -> None:  # pragma: no cover - simple stub
        pass


class _DummyAgent:
    def __init__(self, project: SimpleNamespace | None) -> None:
        self._project = project
        self.serena_config = SimpleNamespace(config_file_path=None)
        self._project_manager = SimpleNamespace(get_last_active_timestamp=lambda name: None)
        self._tool_manager = SimpleNamespace(all_tools={})

    def execute_task(self, func, *, logged: bool | None = None, name: str | None = None):
        del logged, name
        return func()

    def get_active_project(self):
        return self._project

    def get_active_project_by_name(self, name: str):
        return self._project

    def get_all_active_projects(self):
        if self._project is None:
            return {}
        return {"dummy": self._project}

    def shutdown(self):
        pass

    def restart_dashboard(self):
        return "restarted"

    def add_language(self, language, project_name):
        pass

    def remove_language(self, language, project_name):
        pass

    def get_context(self):
        return SimpleNamespace(name="test", description="test")

    def get_active_modes(self):
        return []

    def get_active_tool_names(self):
        return ["list_tools"]

    def get_session_manager(self):
        return SimpleNamespace(
            get_project_session_count=lambda n: 0,
            to_dict_list=lambda: [],
        )

    def get_current_tasks(self):
        return []

    def get_last_executed_task(self):
        return None


def _make_dashboard(project_languages: list[Language] | None) -> SerenaDashboardAPI:
    project = None
    if project_languages is not None:
        project = SimpleNamespace(project_config=SimpleNamespace(languages=project_languages))
    agent = _DummyAgent(project)
    return SerenaDashboardAPI(memory_log_handler=_DummyMemoryLogHandler(), tool_names=[], agent=agent, tool_usage_stats=None)


def _make_client(project_languages=None) -> FlaskClient:
    dashboard = _make_dashboard(project_languages)
    return dashboard._app.test_client()


def test_available_languages_include_experimental_when_no_active_project():
    dashboard = _make_dashboard(project_languages=None)
    response = dashboard._get_available_languages()
    expected = sorted(lang.value for lang in Language.iter_all(include_experimental=True))
    assert response.languages == expected


def test_available_languages_exclude_project_languages():
    dashboard = _make_dashboard(project_languages=[Language.PYTHON, Language.MARKDOWN])
    response = dashboard._get_available_languages()
    available = set(response.languages)
    assert Language.PYTHON.value not in available
    assert Language.MARKDOWN.value not in available
    # ensure experimental languages remain available for selection
    assert Language.ANSIBLE.value in available


# ── DashboardPortFile tests ──────────────────────────────────────────────────


def test_port_file_write_and_read(tmp_path):
    pf = DashboardPortFile(tmp_path / "port")
    pf.write(24282)
    assert pf.read() == 24282


def test_port_file_read_nonexistent(tmp_path):
    pf = DashboardPortFile(tmp_path / "port")
    assert pf.read() is None


def test_port_file_read_corrupt(tmp_path):
    pf = DashboardPortFile(tmp_path / "port")
    pf.path.write_text("garbage")
    assert pf.read() is None


def test_port_file_overwrite(tmp_path):
    pf = DashboardPortFile(tmp_path / "port")
    pf.write(24282)
    pf.write(24283)
    assert pf.read() == 24283


# ── Simple read routes (Flask test client) ────────────────────────────────────


def test_route_heartbeat():
    client = _make_client()
    response = client.get("/heartbeat")
    assert response.status_code == 200
    assert response.get_json() == {"status": "alive"}


def test_route_get_tool_names():
    client = _make_client()
    response = client.get("/get_tool_names")
    assert response.status_code == 200
    data = response.get_json()
    assert "tool_names" in data


def test_route_get_tool_stats():
    client = _make_client()
    response = client.get("/get_tool_stats")
    assert response.status_code == 200
    data = response.get_json()
    assert "stats" in data


def test_route_get_token_count_estimator_name():
    client = _make_client()
    response = client.get("/get_token_count_estimator_name")
    assert response.status_code == 200
    data = response.get_json()
    assert "token_count_estimator_name" in data


# ── Action routes ─────────────────────────────────────────────────────────────


def test_route_clear_tool_stats():
    client = _make_client()
    response = client.post("/clear_tool_stats")
    assert response.status_code == 200
    assert response.get_json() == {"status": "cleared"}


def test_route_clear_logs():
    client = _make_client()
    response = client.post("/clear_logs")
    assert response.status_code == 200
    assert response.get_json() == {"status": "cleared"}


def test_route_get_available_languages_no_project():
    client = _make_client()
    response = client.get("/get_available_languages")
    assert response.status_code == 200
    data = response.get_json()
    assert "languages" in data
    expected = sorted(lang.value for lang in Language.iter_all(include_experimental=True))
    assert data["languages"] == expected


def test_route_redirect():
    client = _make_client()
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard/"


def test_route_serve_dashboard_index():
    client = _make_client()
    response = client.get("/dashboard/")
    assert response.status_code == 200


# ── Error handling tests ──────────────────────────────────────────────────────


def test_route_add_language_no_data():
    client = _make_client()
    response = client.post("/add_language", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "error"


def test_route_remove_language_no_data():
    client = _make_client()
    response = client.post("/remove_language", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "error"


def test_route_get_memory_no_data():
    client = _make_client()
    response = client.post("/get_memory", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "error"


def test_route_save_memory_no_data():
    client = _make_client()
    response = client.post("/save_memory", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "error"


def test_route_delete_memory_no_data():
    client = _make_client()
    response = client.post("/delete_memory", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "error"


def test_route_rename_memory_no_data():
    client = _make_client()
    response = client.post("/rename_memory", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "error"


# ── Handler method tests (direct, not through Flask) ─────────────────────────


def test_get_tool_names():
    dashboard = _make_dashboard(None)
    result = dashboard._get_tool_names()
    assert isinstance(result, ResponseToolNames)
    assert result.tool_names == []


def test_get_tool_stats_with_none():
    dashboard = _make_dashboard(None)
    result = dashboard._get_tool_stats()
    assert isinstance(result, ResponseToolStats)
    assert result.stats == {}


def test_resolve_project_with_name():
    dashboard = _make_dashboard(project_languages=[Language.PYTHON])
    result = dashboard._resolve_project("dummy")
    assert result is not None
    assert result.project_config.languages == [Language.PYTHON]


def test_resolve_project_no_project():
    dashboard = _make_dashboard(None)
    result = dashboard._resolve_project()
    assert result is None


def test_get_available_languages_with_project():
    client = _make_client(project_languages=[Language.PYTHON, Language.MARKDOWN])
    response = client.get("/get_available_languages")
    assert response.status_code == 200
    data = response.get_json()
    available = set(data["languages"])
    assert Language.PYTHON.value not in available
    assert Language.MARKDOWN.value not in available
    assert Language.ANSIBLE.value in available


def test_serialize_log_entry():
    entry = LogEntry(
        message="test message",
        level="INFO",
        logger_name="test_logger",
        created=1234567890.0,
        thread_name="MainThread",
        session_id="sess1",
        project_name="proj1",
        sequence=42,
    )
    result = SerenaDashboardAPI._serialize_log_entry(entry)
    assert result == {
        "sequence": 42,
        "message": "test message",
        "level": "INFO",
        "logger": "test_logger",
        "created": 1234567890.0,
        "thread": "MainThread",
        "session_id": "sess1",
        "project_name": "proj1",
    }


def test_get_log_messages_empty():
    dashboard = _make_dashboard(None)
    result = dashboard._get_log_messages(RequestLog())
    assert isinstance(result, ResponseLog)
    assert result.messages == []
    assert result.max_idx == -1
