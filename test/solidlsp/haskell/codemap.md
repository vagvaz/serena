# test/solidlsp/haskell/

## Responsibility
Tests for the Haskell Language Server (HLS) integration.

## Test Approach
Uses `test_haskell_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for Haskell source files.

## Markers
`@pytest.mark.haskell`
