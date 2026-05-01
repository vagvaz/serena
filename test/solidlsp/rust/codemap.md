# test/solidlsp/rust/

## Responsibility
Tests for the Rust (rust-analyzer) language server integration.

## Test Approach
Three test files: `test_rust_basic.py` (symbol tree, cross-file references, overview methods), `test_rust_2024_edition.py` (Rust 2024 edition feature compatibility), `test_rust_analyzer_detection.py` (rust-analyzer binary detection and configuration). Uses parametrized `language_server` fixture with shared symbol helpers.

## Markers
`@pytest.mark.rust`
