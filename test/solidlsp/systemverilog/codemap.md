# test/solidlsp/systemverilog/

## Responsibility
Tests for the SystemVerilog language server (svlangserver / verible) integration.

## Test Approach
Two test files: `test_systemverilog_basic.py` (basic symbol resolution, module/port detection) and `test_systemverilog_detection.py` (automatic detection of the SystemVerilog server binary). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.systemverilog`
