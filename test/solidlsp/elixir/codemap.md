# test/solidlsp/elixir/

## Responsibility
Tests for the Elixir (Next LS / Elixir LS) language server integration.

## Test Approach
Five test files: `test_elixir_basic.py` (basic symbols), `test_elixir_symbol_retrieval.py` (cross-file symbol query), `test_elixir_integration.py` (references, definitions), `test_elixir_ignored_dirs.py` (ignored path filtering), `test_elixir_startup.py` (server initialization). `conftest.py` provides `setup_elixir_test_environment` (session-scoped, autouse) that runs `mix deps.get` and `mix compile` with generous timeouts to ensure Next LS has a fully compiled project.

## Markers
`@pytest.mark.elixir`
