# test/solidlsp/util/

## Responsibility
Tests for utility modules used by the language server infrastructure — file download with hash verification and safe ZIP extraction.

## Test Approach
- **test_ls_utils.py**: Validates `FileUtils.download_file_verified()` writes the correctly decoded payload body when the HTTP response uses gzip `Content-Encoding`. Uses a mock `requests.get` returning a `_FakeResponse` with gzip headers.
- **test_zip.py**: Tests `SafeZipExtractor` covering successful extraction, include/exclude pattern filtering (both independently and combined), error tolerance (skips failing files, continues extraction), and Windows long-path normalization (`\\?\` prefix).

## Markers
- `pytest.mark.skipif(sys.platform != "win32")` for the long-path normalization test.

## Integration
- Imports from `solidlsp.ls_utils` and `solidlsp.util.zip`.
- `test_ls_utils.py` patches `solidlsp.ls_utils.requests.get` to avoid network calls.
