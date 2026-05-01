# test/solidlsp/zig/

## Responsibility
Tests for the Zig (zls) language server integration.

## Test Approach
Uses `test_zig_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution for Zig source files.

## Markers
`@pytest.mark.zig`
