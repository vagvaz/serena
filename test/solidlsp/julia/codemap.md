# test/solidlsp/julia/

## Responsibility
Tests for the Julia language server integration.

## Test Approach
Uses `test_julia_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for Julia source files.

## Markers
`@pytest.mark.julia`
