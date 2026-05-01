# test/solidlsp/kotlin/

## Responsibility
Tests for the Kotlin language server integration.

## Test Approach
Uses `test_kotlin_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution for Kotlin source files.

## Markers
`@pytest.mark.kotlin`, skipped in CI because Kotlin LSP JVM crashes on restart.
