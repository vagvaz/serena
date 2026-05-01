# test/solidlsp/lean4/

## Responsibility
Tests for the Lean 4 language server integration.

## Test Approach
Uses `test_lean4_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution for Lean 4 source files.

## Markers
`@pytest.mark.lean4`, skipped if `lean` binary is not in PATH.
