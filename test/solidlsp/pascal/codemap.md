# test/solidlsp/pascal/

## Responsibility
Tests for the Pascal language server integration.

## Test Approach
Two test files: `test_pascal_basic.py` (basic symbol resolution) and `test_pascal_auto_update.py` (auto-update mechanism for the Pascal server). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.pascal`
