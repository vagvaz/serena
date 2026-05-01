# test/solidlsp/clojure/

## Responsibility
Tests for the Clojure LSP (clojure-lsp) language server integration.

## Test Approach
Uses `test_clojure_basic.py` with parametrized `language_server` fixture. `__init__.py` checks Clojure CLI availability via `verify_clojure_cli()`. Defines `TEST_APP_PATH`, `CORE_PATH`, `UTILS_PATH` for test file paths. Validates symbol resolution and cross-file references.

## Markers
`@pytest.mark.clojure`, skipped if Clojure CLI is not installed.
