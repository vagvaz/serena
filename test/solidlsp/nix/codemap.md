# test/solidlsp/nix/

## Responsibility
Tests for the Nix (nil) language server integration.

## Test Approach
Uses `test_nix_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for Nix expression files.

## Markers
`@pytest.mark.nix`
