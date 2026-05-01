# test/solidlsp/luau/

## Responsibility
Tests for the Luau language server integration.

## Test Approach
Two test files: `test_luau_basic.py` (basic symbol resolution) and `test_luau_dependency_provider.py` (dependency provider validation). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.luau`
