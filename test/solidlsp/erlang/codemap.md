# test/solidlsp/erlang/

## Responsibility
Tests for the Erlang language server (erlang_ls) integration.

## Test Approach
Three test files: `test_erlang_basic.py` (initialization, document symbols, bare symbol names), `test_erlang_symbol_retrieval.py` (cross-file symbol queries), `test_erlang_ignored_dirs.py` (ignored path filtering). `__init__.py` checks Erlang/OTP and rebar3 availability; sets `ERLANG_LS_UNAVAILABLE` flag. `conftest.py` provides `setup_erlang_test_environment` (session-scoped, autouse) that runs `rebar3 deps` and `rebar3 compile` to prepare the test repository for accurate LS indexing.

## Markers
`@pytest.mark.erlang`, skipped if Erlang LS / OTP / rebar3 is unavailable or on Windows.
