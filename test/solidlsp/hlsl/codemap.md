# test/solidlsp/hlsl/

## Responsibility
Tests for the HLSL language server integration.

## Test Approach
Two test files: `test_hlsl_basic.py` (basic symbol resolution) and `test_hlsl_full_index.py` (full workspace indexing and cross-file symbol retrieval). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.hlsl`
