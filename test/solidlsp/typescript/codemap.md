# test/solidlsp/typescript/

## Responsibility
Tests for the TypeScript/JavaScript (tsserver) language server integration.

## Test Approach
Uses `test_typescript_basic.py` with parametrized `language_server` fixture. Covers: symbol tree completeness, cross-file references, JSX symbol range regression test (ensuring `.tsx` files use correct `languageId`), and bare symbol name validation. Uses shared symbol helpers from `test.solidlsp.conftest`.

## Markers
`@pytest.mark.typescript`
