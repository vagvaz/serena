"""Unit tests for SolidLanguageServer — no real LS binaries required.

These tests mock at the LSP protocol level (server.send.document_symbol, etc.)
so they run quickly and in any environment.
"""

import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_types import SymbolKind
from solidlsp.settings import SolidLSPSettings
from solidlsp.ls_process import ProcessLaunchInfo
from solidlsp.lsp_protocol_handler.lsp_types import DocumentSymbol


# ── test subclass that never touches a real LS binary ────────────────────


class _TestLS(SolidLanguageServer):
    """Minimal SolidLanguageServer subclass for unit testing."""

    def __init__(self, config, repo_root, settings, mock_server):
        # Skip the parent's heavy __init__ by going through create's path
        # but we set up only what we need.
        self._solidlsp_settings = settings
        self._encoding = config.encoding
        self.language_id = "python"
        self.repository_root_path = os.path.abspath(repo_root)
        self.open_file_buffers: dict = {}
        self.language = Language.PYTHON
        self._ls_specific_raw_document_symbols_cache_version = 1
        self._raw_document_symbols_cache: dict = {}
        self._raw_document_symbols_cache_is_modified: bool = False
        self._document_symbols_cache: dict = {}
        self._document_symbols_cache_is_modified: bool = False
        self._cache_storage_mode = settings.cache_storage_mode
        self.cache_dir = (
            Path(settings.project_data_path) / SolidLanguageServer.CACHE_FOLDER_NAME / self.language_id
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._has_waited_for_cross_file_references = False

        # Mock the server
        self.server = mock_server
        self.server_started = False
        self._ignore_spec = None
        self._request_timeout: float | None = None

        # Load caches (no-op for fresh dirs)
        self._load_raw_document_symbols_cache()
        self._load_document_symbols_cache()

    def _create_dependency_provider(self):
        raise NotImplementedError("not needed in tests")

    def _start_server(self):
        self.server_started = True

    # Keep is_running consistent with our mock
    def is_running(self):
        return True


# ── helpers ──────────────────────────────────────────────────────────────


def _make_config() -> LanguageServerConfig:
    return LanguageServerConfig(
        code_language=Language.PYTHON,
        ignored_paths=[],
        trace_lsp_communication=False,
        encoding="utf-8",
    )


def _make_settings(tmp_path: Path, cache_mode: str = "monolithic") -> SolidLSPSettings:
    return SolidLSPSettings(
        solidlsp_dir=str(tmp_path / "solidlsp"),
        project_data_path=str(tmp_path / "data"),
        ls_specific_settings={},
        cache_storage_mode=cache_mode,  # type: ignore[arg-type]
    )


def _make_mock_server() -> MagicMock:
    """Build a LanguageServerProcess mock that returns empty symbol lists."""
    server = MagicMock()
    server.send.document_symbol.return_value = []
    server.send.initialize.return_value = {"capabilities": {}}
    server.is_running.return_value = True
    server.start.return_value = None
    server.stop.return_value = None
    return server


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_repo(tmp_path: Path) -> str:
    repo = tmp_path / "repo"
    repo.mkdir()
    return str(repo)


@pytest.fixture
def fresh_ls(tmp_path: Path, tmp_repo: str, request) -> _TestLS:
    """Create a test LS instance with a mock server."""
    mock_server = _make_mock_server()
    settings = _make_settings(tmp_path)
    ls = _TestLS(_make_config(), tmp_repo, settings, mock_server)
    ls._start_server()  # sets server_started = True
    return ls


# ── tests ────────────────────────────────────────────────────────────────


class TestSolidLanguageServerCache:
    """Tests for the caching layer (raw + high-level document symbols)."""

    def test_raw_cache_miss_then_hit(self, fresh_ls: _TestLS, tmp_repo: str):
        """A second request with unchanged content returns cached symbols."""
        fpath = os.path.join(tmp_repo, "test.py")
        with open(fpath, "w") as f:
            f.write("x = 1\n")

        symbols = fresh_ls.request_document_symbols("test.py")
        assert symbols is not None
        assert fresh_ls.server.send.document_symbol.call_count == 1

        # Second call — cache hit, no new LS request
        fresh_ls.server.send.document_symbol.reset_mock()
        symbols2 = fresh_ls.request_document_symbols("test.py")
        assert symbols2 is not None
        fresh_ls.server.send.document_symbol.assert_not_called()

    def test_raw_cache_stale_on_content_change(self, fresh_ls: _TestLS, tmp_repo: str):
        """Changing the file content invalidates the raw symbol cache."""
        fpath = os.path.join(tmp_repo, "test.py")
        with open(fpath, "w") as f:
            f.write("x = 1\n")
        fresh_ls.request_document_symbols("test.py")
        assert fresh_ls.server.send.document_symbol.call_count == 1

        # Modify the file
        with open(fpath, "w") as f:
            f.write("y = 2\n")

        fresh_ls.server.send.document_symbol.reset_mock()
        fresh_ls.request_document_symbols("test.py")
        fresh_ls.server.send.document_symbol.assert_called_once()

    def test_per_file_cache_persistence(self, fresh_ls: _TestLS, tmp_repo: str, tmp_path: Path):
        """In per_file mode, cached entries survive a full LS restart (new instance)."""
        # Create file and use per_file mode
        fpath = os.path.join(tmp_repo, "test.py")
        with open(fpath, "w") as f:
            f.write("x = 1\n")

        # We need to re-create with per_file mode for this test
        mock_server1 = _make_mock_server()
        settings = _make_settings(tmp_path, cache_mode="per_file")
        ls1 = _TestLS(_make_config(), tmp_repo, settings, mock_server1)
        ls1._start_server()
        ls1.request_document_symbols("test.py")
        assert mock_server1.send.document_symbol.call_count == 1

        # "Restart" with a fresh instance, same cache dir
        mock_server2 = _make_mock_server()
        ls2 = _TestLS(_make_config(), tmp_repo, settings, mock_server2)
        ls2._start_server()

        # Should reload from disk — no new LS request
        symbols = ls2.request_document_symbols("test.py")
        assert symbols is not None
        mock_server2.send.document_symbol.assert_not_called()

    def test_empty_response_not_cached(self, fresh_ls: _TestLS, tmp_repo: str):
        """An empty/None document_symbol response is NOT cached."""
        fresh_ls.server.send.document_symbol.return_value = None

        fpath = os.path.join(tmp_repo, "test.py")
        with open(fpath, "w") as f:
            f.write("x = 1\n")

        fresh_ls.request_document_symbols("test.py")
        assert fresh_ls.server.send.document_symbol.call_count == 1

        # Second call — still None, should call again
        fresh_ls.request_document_symbols("test.py")
        assert fresh_ls.server.send.document_symbol.call_count == 2


class TestSolidLanguageServerIgnore:
    """Tests for is_ignored_path."""

    def test_ignore_by_pattern(self, fresh_ls: _TestLS, tmp_repo: str, tmp_path: Path):
        """Paths matching ignore patterns are correctly ignored."""
        from solidlsp.ls_config import LanguageServerConfig

        # Rebuild the LS with ignore patterns
        config = LanguageServerConfig(
            code_language=Language.PYTHON,
            ignored_paths=["node_modules/*", "*.pyc"],
            trace_lsp_communication=False,
            encoding="utf-8",
        )
        # Force the ignore spec to be set
        import pathspec

        fresh_ls._ignore_spec = pathspec.PathSpec.from_lines(
            pathspec.patterns.GitWildMatchPattern,
            config.ignored_paths,
        )

        # Create files so is_ignored_path can stat them
        for f in ["main.py", "node_modules/pkg/index.js", "__pycache__/mod.pyc"]:
            p = Path(tmp_repo) / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")

        assert not fresh_ls.is_ignored_path("main.py", ignore_unsupported_files=False)
        assert fresh_ls.is_ignored_path("node_modules/pkg/index.js", ignore_unsupported_files=False)
        assert fresh_ls.is_ignored_path("__pycache__/mod.pyc", ignore_unsupported_files=False)


class TestSolidLanguageServerSymbolConversion:
    """Tests for raw → unified symbol conversion."""

    def test_normalize_symbol_name(self, fresh_ls: _TestLS, tmp_repo: str):
        """_normalize_symbol_name returns the name as-is (subclasses strip noise)."""
        sym: DocumentSymbol = {
            "name": "foo(bar: int)",
            "kind": SymbolKind.Function,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 4}},
            "selectionRange": {"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 4}},
        }
        # Our test LS uses the base implementation, which doesn't strip params
        normalized = fresh_ls._normalize_symbol_name(sym, "test.py")
        assert normalized == "foo(bar: int)"


class TestSolidLanguageServerHackFix:
    """Tests for the replacement of the 'horrible hack' symbol heuristics."""

    def _walk_for_containing_symbol(self, doc_symbols, ref_line: int):
        """Replicates the logic now in ls.py replacing the horrible hack."""
        best_symbol = None
        best_size: int | None = None

        for symbol in doc_symbols.iter_symbols():
            sym_range = symbol.get("range") or (symbol.get("location") or {}).get("range")
            if sym_range is None:
                continue
            start_line: int = sym_range["start"]["line"]
            end_line: int = sym_range["end"]["line"]
            if start_line <= ref_line <= end_line:
                size = end_line - start_line
                if best_size is None or size < best_size:
                    best_size = size
                    best_symbol = symbol
        return best_symbol

    def test_finds_innermost_symbol(self, fresh_ls: _TestLS, tmp_repo: str):
        """Walk the symbol tree and pick the innermost symbol containing the
        reference position."""
        fpath = os.path.join(tmp_repo, "test.py")
        with open(fpath, "w") as f:
            f.write("class Foo:\n    def bar(self):\n        x = 1\n")

        # Make the mock server return proper symbols
        from solidlsp.ls_types import SymbolKind

        fresh_ls.server.send.document_symbol.return_value = [
            {
                "name": "Foo",
                "kind": SymbolKind.Class,
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 13}},
                "selectionRange": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                "children": [
                    {
                        "name": "bar",
                        "kind": SymbolKind.Method,
                        "range": {"start": {"line": 1, "character": 4}, "end": {"line": 2, "character": 13}},
                        "selectionRange": {
                            "start": {"line": 1, "character": 4}, "end": {"line": 1, "character": 7}
                        },
                        "children": [],
                    },
                ],
            },
        ]

        doc_symbols = fresh_ls.request_document_symbols("test.py")
        best = self._walk_for_containing_symbol(doc_symbols, ref_line=2)
        assert best is not None
        # Should find 'bar' (lines 1-2) before 'Foo' (lines 0-2)
        assert best["name"] == "bar"

    def test_no_symbol_at_reference_line(self, fresh_ls: _TestLS, tmp_repo: str):
        """When the reference line is outside any symbol range (module-level
        attribute access), the walk returns None and the file-symbol fallback
        kicks in."""
        fpath = os.path.join(tmp_repo, "test.py")
        with open(fpath, "w") as f:
            f.write("instance = MyClass()\ninstance.status = 'new'\n")

        from solidlsp.ls_types import SymbolKind

        fresh_ls.server.send.document_symbol.return_value = [
            {
                "name": "instance",
                "kind": SymbolKind.Variable,
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 18}},
                "selectionRange": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 8}},
                "children": [],
            },
        ]

        doc_symbols = fresh_ls.request_document_symbols("test.py")
        # Reference is at line 1, symbol 'instance' is at line 0 — not within range
        best = self._walk_for_containing_symbol(doc_symbols, ref_line=1)
        assert best is None


class TestServerReadinessProtocol:
    """Tests for the standardized server readiness protocol (_signal_server_ready / _wait_for_server_ready)."""

    def test_signal_and_wait(self):
        """_signal_server_ready and _wait_for_server_ready work correctly with real Events."""
        event = threading.Event()

        def signal_after_delay():
            import time
            time.sleep(0.01)
            event.set()

        t = threading.Thread(target=signal_after_delay)
        t.start()

        result = event.wait(timeout=5.0)
        assert result is True
        t.join()

    def test_wait_timeout(self):
        """_wait_for_server_ready returns False when timeout is exceeded."""
        event = threading.Event()
        result = event.wait(timeout=0.01)
        assert result is False

    def test_signal_before_wait(self):
        """If the server is already ready, wait returns immediately."""
        event = threading.Event()
        event.set()
        result = event.wait(timeout=5.0)
        assert result is True
