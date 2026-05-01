# test/solidlsp/powershell/

## Responsibility
Tests for the PowerShell language server integration.

## Test Approach
Uses `test_powershell_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for PowerShell scripts.

## Markers
`@pytest.mark.powershell`
