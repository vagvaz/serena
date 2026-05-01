# test/solidlsp/go/

## Responsibility
Tests for the Go (gopls) language server integration.

## Test Approach
Uses `test_go_basic.py` with parametrized `language_server` fixture covering: symbol tree completeness, Go method bare-name normalization (receiver-qualified names stripped), cross-file references, build tag/constraint support (`-tags=foo` switching symbols in/out), and disk cache invalidation on build context switches. Uses fixture repo copies (via `shutil.copytree`) for build tag tests to avoid side effects.

## Markers
`@pytest.mark.go`
