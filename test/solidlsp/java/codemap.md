# test/solidlsp/java/

## Responsibility
Tests for the Java (Eclipse JDT LS) language server integration.

## Test Approach
Two test files: `test_java_basic.py` (symbol resolution, document symbols) and `test_jdtls_path_resolution.py` (JDT LS path and workspace resolution logic). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.java`
