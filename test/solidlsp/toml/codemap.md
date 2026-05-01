# test/solidlsp/toml/

## Responsibility
Tests for the TOML (taplo) language server integration.

## Test Approach
Four test files: `test_toml_basic.py` (basic symbol resolution), `test_toml_symbol_retrieval.py` (workspace symbol queries), `test_toml_ignored_dirs.py` (symbol resolution respects ignored path patterns), `test_toml_edge_cases.py` (edge cases in TOML parsing and symbol reporting). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.toml`
