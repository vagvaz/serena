# test/solidlsp/rego/

## Responsibility
Tests for the Rego (Open Policy Agent) language server integration.

## Test Approach
Uses `test_rego_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution for Rego policy files.

## Markers
`@pytest.mark.rego`
