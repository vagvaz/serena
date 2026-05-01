# src/solidlsp/lsp_protocol_handler/

## Responsibility
Low-level JSON-RPC 2.0 / LSP protocol implementation: message serialization, LSP type definitions, and generated interfaces for all LSP requests and notifications (LSP v3.17.0).

## Key Files
- `lsp_constants.py` — `LSPConstants`: string constants for common LSP dictionary keys (`uri`, `range`, `textDocument`, `position`, etc.).
- `lsp_requests.py` — `LspRequest` (async) and `LspNotification`: generated Python bindings for every LSP method (e.g. `textDocument/definition`, `textDocument/didOpen`). Each method builds the correct JSON-RPC message and delegates to a send function.
- `lsp_types.py` — 5943-line generated module with all LSP v3.17.0 types: `Position`, `Range`, `Location`, `SymbolKind`, `DocumentSymbol`, `InitializeParams`, error codes, semantic token types, etc. Defined as `TypedDict` and `IntEnum` classes.
- `server.py` — JSON-RPC core: `ProcessLaunchInfo` (command/env/cwd), `LSPError` (error code + message), and helper functions for message construction (`make_request`, `make_notification`, `make_response`, `make_error_response`, `create_message`, `content_length`).

## Design Patterns
- **Generated Bindings**: Both `lsp_types.py` and `lsp_requests.py` are auto-generated from the LSP TypeScript specification using [OLSP](https://github.com/predragnikolic/OLSP), ensuring faithful protocol coverage.
- **Function Composition**: Low-level helpers (`create_message`, `content_length`) are composed by `LanguageServerProcess` in `ls_process.py`; `LspRequest`/`LspNotification` are independent of the transport layer.
- **TypedDict for Types**: All LSP types are `TypedDict` subclasses, enabling static type checking of JSON payloads without runtime overhead.
- **Void-Method Awareness**: `_build_params_field` in `server.py` omits `params` entirely for methods like `shutdown`/`exit` that use unit/Void type, accommodating HLS and rust-analyzer.

## Flow
1. `server.py` provides pure functions that construct JSON-RPC 2.0 message tuples (`(header, content-type, body)`).
2. `LanguageServerProcess` (in `ls_process.py`) uses `content_length` to parse incoming headers and `create_message` to serialize outgoing payloads.
3. `LspRequest` (async) and `LspNotification` are instantiated by `LanguageServerProcess` and exposed as `.send` and `.notify` attributes, providing a clean typed API for the rest of solidlsp.

## Integration
- Consumed by: `solidlsp.ls_process.py` (core communication), `solidlsp.ls_request.py` (synchronous request layer), `solidlsp.ls.py` (LSP constant / type imports)
- Depends on: nothing outside the package (self-contained protocol layer)
