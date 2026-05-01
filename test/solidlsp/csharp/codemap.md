# test/solidlsp/csharp/

## Responsibility
Tests for the C# (OmniSharp) language server integration.

## Test Approach
Uses `test_csharp_basic.py` with parametrized `language_server` fixture for basic symbol resolution. `test_csharp_nuget_download.py` tests NuGet package download logic with mocked HTTP responses.

## Markers
`@pytest.mark.csharp`
