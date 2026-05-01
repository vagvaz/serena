# test/solidlsp/vue/

## Responsibility
Tests for the Vue (Volar) language server integration.

## Test Approach
Four test files: `test_vue_basic.py` (basic symbol resolution), `test_vue_symbol_retrieval.py` (workspace symbol queries), `test_vue_rename.py` (rename refactoring across `.vue` files), `test_vue_error_cases.py` (error handling and edge cases). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.vue`
