"""Tests for LanguageServerManager and LanguageServerFactory."""

from typing import Any

import pytest

from serena.ls_manager import LanguageServerFactory, LanguageServerManager, LanguageServerManagerInitialisationError
from solidlsp.ls_config import Language


class _FakeLanguageServer:
    """Minimal fake satisfying the SolidLanguageServer interface used by LanguageServerManager."""

    def __init__(self, language: Language, running: bool = True, ignored_paths: set[str] | None = None) -> None:
        self.language = language
        self._running = running
        self._stopped = False
        self._cache_saved = False
        self._ignored_paths = ignored_paths or set()
        self.start_called = False

    def is_running(self) -> bool:
        return self._running and not self._stopped

    def is_ignored_path(self, path: str, ignore_unsupported_files: bool = False) -> bool:
        del ignore_unsupported_files
        return path in self._ignored_paths

    def stop(self, shutdown_timeout: float = 2.0) -> None:
        del shutdown_timeout
        self._stopped = True

    def save_cache(self) -> None:
        self._cache_saved = True

    def start(self) -> None:
        self.start_called = True
        self._running = True


class _FakeLanguageServerFactory:
    """Fake factory that creates _FakeLanguageServer instances."""

    def __init__(self, default_running: bool = True, default_ignored_paths: set[str] | None = None) -> None:
        self.default_running = default_running
        self.default_ignored_paths = default_ignored_paths or set()
        self.created: list[Language] = []

    def create_language_server(self, language: Language) -> _FakeLanguageServer:
        self.created.append(language)
        return _FakeLanguageServer(
            language=language,
            running=self.default_running,
            ignored_paths=set(self.default_ignored_paths),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _manager(
    languages: list[Language],
    running: bool = True,
) -> tuple[LanguageServerManager, _FakeLanguageServerFactory]:
    factory = _FakeLanguageServerFactory(default_running=running)
    servers = {lang: factory.create_language_server(lang) for lang in languages}
    return LanguageServerManager(servers, factory), factory


# ── Empty / default ───────────────────────────────────────────────────────────


def test_empty_manager_raises_on_default():
    manager = LanguageServerManager({})
    with pytest.raises(ValueError, match="No language servers available"):
        _ = manager._default_language_server


def test_default_language_server():
    manager, _ = _manager([Language.PYTHON])
    assert manager._default_language_server.language == Language.PYTHON


# ── get_language_server ───────────────────────────────────────────────────────


def test_get_language_server_single():
    """Single server always returns itself regardless of path."""
    manager, _ = _manager([Language.PYTHON])
    ls = manager.get_language_server("some/file.py")
    assert ls.language == Language.PYTHON


def test_get_language_server_multi_selects_suitable():
    """When multiple servers exist, picks the one that does NOT ignore the path."""
    ignored = {"some/file.py"}
    py = _FakeLanguageServer(Language.PYTHON, ignored_paths=ignored)
    md = _FakeLanguageServer(Language.MARKDOWN, ignored_paths=set())
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    ls = manager.get_language_server("some/file.py")
    assert ls.language == Language.MARKDOWN


def test_get_language_server_falls_back_to_default():
    """When all servers ignore the path, returns the default (first)."""
    ignored = {"some/file.py"}
    py = _FakeLanguageServer(Language.PYTHON, ignored_paths=ignored)
    md = _FakeLanguageServer(Language.MARKDOWN, ignored_paths=ignored)
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    ls = manager.get_language_server("some/file.py")
    assert ls.language == Language.PYTHON


def test_get_language_server_directory_raises():
    """Multi-server manager raises for directory paths."""
    manager, _ = _manager([Language.PYTHON, Language.MARKDOWN])
    with pytest.raises(ValueError, match="Expected a file path"):
        manager.get_language_server("src/")


# ── _ensure_functional_ls ─────────────────────────────────────────────────────


def test_ensure_functional_ls_alive():
    manager, factory = _manager([Language.PYTHON])
    ls = manager._ensure_functional_ls(manager._default_language_server)
    assert ls.is_running()


def test_ensure_functional_ls_restarts_dead():
    py = _FakeLanguageServer(Language.PYTHON, running=False)
    manager = LanguageServerManager({Language.PYTHON: py}, _FakeLanguageServerFactory())
    restarted = manager._ensure_functional_ls(py)
    assert restarted.is_running()
    assert restarted.start_called


# ── restart_language_server ───────────────────────────────────────────────────


def test_restart_language_server():
    py = _FakeLanguageServer(Language.PYTHON)
    factory = _FakeLanguageServerFactory()
    manager = LanguageServerManager({Language.PYTHON: py}, factory)
    restarted = manager.restart_language_server(Language.PYTHON)
    assert restarted.language == Language.PYTHON
    assert restarted is not py
    assert restarted.is_running()
    assert Language.PYTHON in factory.created


def test_restart_nonexistent_raises():
    manager, _ = _manager([Language.PYTHON])
    with pytest.raises(ValueError, match="cannot restart"):
        manager.restart_language_server(Language.MARKDOWN)


# ── add / remove ──────────────────────────────────────────────────────────────


def test_add_language_server():
    manager, factory = _manager([Language.PYTHON])
    new_ls = manager.add_language_server(Language.MARKDOWN)
    assert new_ls.language == Language.MARKDOWN
    assert manager.get_active_languages() == [Language.PYTHON, Language.MARKDOWN]


def test_add_duplicate_raises():
    manager, _ = _manager([Language.PYTHON])
    with pytest.raises(ValueError, match="already present"):
        manager.add_language_server(Language.PYTHON)


def test_remove_language_server():
    py = _FakeLanguageServer(Language.PYTHON)
    manager = LanguageServerManager({Language.PYTHON: py})
    manager.remove_language_server(Language.PYTHON)
    assert manager.get_active_languages() == []
    assert not py.is_running()


def test_remove_language_server_saves_cache():
    py = _FakeLanguageServer(Language.PYTHON)
    manager = LanguageServerManager({Language.PYTHON: py})
    manager.remove_language_server(Language.PYTHON, save_cache=True)
    assert py._cache_saved


def test_remove_nonexistent_raises():
    manager, _ = _manager([Language.PYTHON])
    with pytest.raises(ValueError, match="cannot remove"):
        manager.remove_language_server(Language.MARKDOWN)


# ── lifecycle ─────────────────────────────────────────────────────────────────


def test_stop_all():
    py = _FakeLanguageServer(Language.PYTHON)
    md = _FakeLanguageServer(Language.MARKDOWN)
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    manager.stop_all()
    assert not py.is_running()
    assert not md.is_running()


def test_stop_all_saves_cache():
    py = _FakeLanguageServer(Language.PYTHON)
    md = _FakeLanguageServer(Language.MARKDOWN)
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    manager.stop_all(save_cache=True)
    assert py._cache_saved
    assert md._cache_saved


def test_save_all_caches():
    py = _FakeLanguageServer(Language.PYTHON)
    md = _FakeLanguageServer(Language.MARKDOWN)
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    manager.save_all_caches()
    assert py._cache_saved
    assert md._cache_saved


def test_is_running_true():
    manager, _ = _manager([Language.PYTHON])
    assert manager.is_running()


def test_is_running_false():
    """is_running returns False after all servers are removed."""
    factory = _FakeLanguageServerFactory()
    manager = LanguageServerManager.from_languages([Language.PYTHON], factory)
    assert manager.is_running()
    manager.remove_language_server(Language.PYTHON)
    assert not manager.is_running()


def test_get_active_languages():
    manager, _ = _manager([Language.PYTHON, Language.MARKDOWN])
    assert set(manager.get_active_languages()) == {Language.PYTHON, Language.MARKDOWN}


# ── circuit breaker ───────────────────────────────────────────────────────────


def test_circuit_breaker_lazy_creation():
    manager, _ = _manager([Language.PYTHON])
    cb = manager.get_circuit_breaker(Language.PYTHON)
    assert cb is not None
    assert cb._name == "python"


def test_circuit_breaker_same_instance():
    manager, _ = _manager([Language.PYTHON])
    cb1 = manager.get_circuit_breaker(Language.PYTHON)
    cb2 = manager.get_circuit_breaker(Language.PYTHON)
    assert cb1 is cb2


def test_reset_circuit_breaker():
    manager, _ = _manager([Language.PYTHON])
    cb = manager.get_circuit_breaker(Language.PYTHON)
    # Trip the breaker by recording enough failures
    for _ in range(cb._threshold):
        cb.record_failure()
    assert cb.is_open()
    manager.reset_circuit_breaker(Language.PYTHON)
    assert not cb.is_open()


def test_reset_circuit_breaker_nonexistent():
    """Resetting a breaker that was never created is a no-op."""
    manager, _ = _manager([Language.PYTHON])
    manager.reset_circuit_breaker(Language.MARKDOWN)  # should not raise


# ── from_languages ────────────────────────────────────────────────────────────


def test_from_languages():
    factory = _FakeLanguageServerFactory()
    manager = LanguageServerManager.from_languages([Language.PYTHON, Language.MARKDOWN], factory)
    assert Language.PYTHON in factory.created
    assert Language.MARKDOWN in factory.created
    assert manager.get_active_languages() == [Language.PYTHON, Language.MARKDOWN]


def test_from_languages_startup_failure():
    """When any server fails, all started servers are stopped and an error is raised."""

    class _FailingServer:
        language = Language.MARKDOWN

        def is_running(self) -> bool:
            return False

        def start(self) -> None:
            raise RuntimeError("boom")

        def stop(self, shutdown_timeout: float = 2.0) -> None:
            pass

        def save_cache(self) -> None:
            pass

        def is_ignored_path(self, path: str, **kwargs: Any) -> bool:
            return False

    class _MixedFactory:
        def __init__(self) -> None:
            self.created_py = _FakeLanguageServer(Language.PYTHON)
            self.py_stopped = False

        def create_language_server(self, language: Language) -> Any:
            if language == Language.PYTHON:
                return self.created_py
            return _FailingServer()

    factory = _MixedFactory()
    with pytest.raises(LanguageServerManagerInitialisationError, match="Failed to start"):
        LanguageServerManager.from_languages([Language.PYTHON, Language.MARKDOWN], factory)
    # The Python server that started successfully must be stopped
    assert not factory.created_py.is_running()


# ── _get_suitable_language_server / has_suitable_ls_for_file ──────────────────


def test_get_suitable_language_server():
    ignored = {"some/file.py"}
    py = _FakeLanguageServer(Language.PYTHON, ignored_paths=ignored)
    md = _FakeLanguageServer(Language.MARKDOWN, ignored_paths=set())
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    result = manager._get_suitable_language_server("some/file.py")
    assert result is not None
    assert result.language == Language.MARKDOWN


def test_get_suitable_language_server_none():
    ignored = {"some/file.py"}
    py = _FakeLanguageServer(Language.PYTHON, ignored_paths=ignored)
    md = _FakeLanguageServer(Language.MARKDOWN, ignored_paths=ignored)
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    result = manager._get_suitable_language_server("some/file.py")
    assert result is None


def test_has_suitable_ls_for_file():
    py = _FakeLanguageServer(Language.PYTHON, ignored_paths={"some/file.py"})
    md = _FakeLanguageServer(Language.MARKDOWN, ignored_paths={"other/file.rs"})
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    assert manager.has_suitable_ls_for_file("some/file.py")  # md handles it
    assert manager.has_suitable_ls_for_file("other/file.rs")  # py handles it
    # When both ignore, no server is suitable
    both = _FakeLanguageServer(Language.PYTHON, ignored_paths={"all.py"})
    both2 = _FakeLanguageServer(Language.MARKDOWN, ignored_paths={"all.py"})
    m2 = LanguageServerManager({Language.PYTHON: both, Language.MARKDOWN: both2})
    assert not m2.has_suitable_ls_for_file("all.py")


# ── iter_language_servers ─────────────────────────────────────────────────────


def test_iter_language_servers():
    py = _FakeLanguageServer(Language.PYTHON)
    md = _FakeLanguageServer(Language.MARKDOWN)
    manager = LanguageServerManager({Language.PYTHON: py, Language.MARKDOWN: md})
    servers = list(manager.iter_language_servers())
    assert len(servers) == 2
    assert {s.language for s in servers} == {Language.PYTHON, Language.MARKDOWN}


def test_iter_language_servers_restarts_dead():
    py = _FakeLanguageServer(Language.PYTHON, running=False)
    factory = _FakeLanguageServerFactory()
    manager = LanguageServerManager({Language.PYTHON: py}, factory)
    servers = list(manager.iter_language_servers())
    assert len(servers) == 1
    assert servers[0].is_running()
    assert servers[0] is not py  # was replaced


# ── LanguageServerFactory ─────────────────────────────────────────────────────


def test_factory_create():
    factory = LanguageServerFactory(
        project_root="/tmp/test",
        project_data_path="/tmp/test/.serena",
        encoding="utf-8",
        ignored_patterns=[],
    )
    # This will try to start a real language server, so we only test the creation
    # part by checking the factory doesn't crash on construction.
    assert factory.project_root == "/tmp/test"
    assert factory.encoding == "utf-8"
    # Note: full create_language_server test requires real LS binary
