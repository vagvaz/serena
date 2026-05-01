# test/solidlsp/ocaml/

## Responsibility
Tests for the OCaml language server integration.

## Test Approach
Two test files: `test_ocaml_basic.py` (basic symbol resolution) and `test_cross_file_refs.py` (inter-file reference resolution). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.ocaml`
