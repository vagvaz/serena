# test/solidlsp/cpp/

## Responsibility
Tests for C/C++ language servers — clangd (`Language.CPP`) and ccls (`Language.CPP_CCLS`).

## Test Approach
Uses `test_cpp_basic.py` with parametrized `language_server` fixture testing both backends. Covers symbol tree completeness, document symbols, cross-file references, cache persistence/invalidation across context changes, and references in newly written files. `test_clangd_logging.py` tests clangd-specific logging behavior. Dynamically detects ccls availability to build the parametrized server list.

## Markers
`@pytest.mark.cpp`, skipped if neither clangd nor ccls is available.
