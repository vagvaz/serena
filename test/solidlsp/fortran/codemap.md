# test/solidlsp/fortran/

## Responsibility
Tests for the Fortran language server integration.

## Test Approach
Uses `test_fortran_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for Fortran source files.

## Markers
`@pytest.mark.fortran`
