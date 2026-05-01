# test/solidlsp/python/

## Responsibility
Tests for Python language servers — basedpyright (`Language.PYTHON`), pyright (`Language.PYTHON_TY`), and Jedi (`Language.PYTHON_JEDI`).

## Test Approach
Three test files: `test_python_basic.py` (references, content retrieval, file search, bare symbol names), `test_symbol_retrieval.py` (containing symbol, referencing symbols, workspace symbols), `test_retrieval_with_ignored_dirs.py` (symbol resolution respects ignored path patterns). Tests cover multiple Python backends via `PYTHON_BACKEND_LANGUAGES` parametrization. Uses the shared `request_all_symbols` / `has_malformed_name` helpers from `test.solidlsp.conftest`.

## Markers
`@pytest.mark.python`
