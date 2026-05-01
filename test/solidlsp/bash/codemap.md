# test/solidlsp/bash/

## Responsibility
Tests for the Bash language server integration.

## Test Approach
Uses `test_bash_basic.py` with parametrized `language_server` fixture. Validates document symbols, references, and symbol tree completeness for shell scripts.

## Markers
`@pytest.mark.bash`
