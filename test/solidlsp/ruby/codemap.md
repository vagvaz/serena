# test/solidlsp/ruby/

## Responsibility
Tests for the Ruby (Solargraph) language server integration.

## Test Approach
Two test files: `test_ruby_basic.py` (symbol tree, cross-file definitions, referencing symbols) and `test_ruby_symbol_retrieval.py` (workspace symbol queries). Uses parametrized `language_server` fixture with shared symbol helpers.

## Markers
`@pytest.mark.ruby`
