# test/solidlsp/

## Responsibility
Integration tests for the `solidlsp` package — the multi-language LSP client abstraction layer. Tests validate document symbols, references, definitions, rename, and cache behavior across 50+ language servers.

## Key Files
- **`conftest.py`**: Common test helpers — `request_all_symbols()`, `has_malformed_name()`, `format_symbol_for_assert()`, and `PYTHON_BACKEND_LANGUAGES` list.
- **`test_ls_common.py`**: Tests for `SolidLanguageServer` base class features (open-file buffer cache invalidation on external file changes).
- **`test_lsp_protocol_handler_server.py`**: Tests for JSON-RPC 2.0 params field handling — Void-type methods (`shutdown`, `exit`) omit `params`, others include `{}` for `None`.
- **`test_rename_didopen.py`**: Verifies `request_rename_symbol_edit` sequence: didOpen → rename → didClose.
- **`util/test_ls_utils.py`**: Tests for `FileUtils.download_file_verified()` with gzip-encoded HTTP responses.
- **`util/test_zip.py`**: Tests for `SafeZipExtractor` — include/exclude patterns, error tolerance, Windows long-path normalization.

## Design Patterns
- **Language-specific subdirectories**: Each of the 50+ language servers has its own package with `test_<lang>_basic.py` as the entry point.
- **Parametrized fixtures**: `language_server` and `project` fixtures are parametrized with `Language` enum values, using the corresponding test repo from `resources/repos/`.
- **Shared symbol helpers**: `request_all_symbols()` flattens the symbol tree; `has_malformed_name()` checks for unwanted characters; `format_symbol_for_assert()` creates readable error messages.
- **Environment-aware skipping**: Each language directory imports availability checks from its `__init__.py`; `_LANGUAGE_PYTEST_MARKERS` in root `conftest.py` provides per-language markers and CI skip logic.

## Flow
```
solidlsp/conftest.py (shared helpers: request_all_symbols, has_malformed_name)
  ├── test_ls_common.py               → base class: cache invalidation
  ├── test_lsp_protocol_handler_server.py → JSON-RPC params handling
  ├── test_rename_didopen.py          → didOpen/rename/didClose sequence
  ├── util/                           → download, zip extraction
  └── <lang>/                         → language-specific tests (50+ dirs)
```

## Integration
- All tests depend on the `solidlsp` package for LSP client implementation.
- Test repositories live in `test/resources/repos/<language>/test_repo/`.
- Languages with build requirements (Elixir, Erlang) provide local `conftest.py` for `mix compile` / `rebar3 compile`.
