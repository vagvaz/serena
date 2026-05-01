# test/solidlsp/msl/

## Responsibility
Tests for the MSL (Modelica Scripting Language) language server integration.

## Test Approach
Uses `test_msl_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for MSL source files.

## Markers
`@pytest.mark.msl`
