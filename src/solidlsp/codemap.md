# src/solidlsp/

## Responsibility
Core LSP framework that manages language server lifecycle (start/stop), file buffer tracking, symbol caching, and high-level LSP requests (definition, references, implementation). Provides `SolidLanguageServer` as the abstract base that all language-specific servers subclass.

## Key Files
- `__init__.py` — Exports `SolidLanguageServer` as the package's public API.
- `ls.py` — Central module: `SolidLanguageServer` (ABC), `LSPFileBuffer` (in-memory file tracking), `SymbolBody`/`DocumentSymbols` (symbol tree representation), and nested request classes (`DefinitionLocationRequest`, `ReferencesLocationRequest`).
- `ls_config.py` — `Language` enum (60+ supported languages), `FilenameMatcher` (fnmatch-based), and `LanguageServerConfig` dataclass.
- `ls_exceptions.py` — `SolidLSPException` (wraps LSP errors / process termination) and `MetalsStaleLockError`.
- `ls_process.py` — `LanguageServerProcess`: launches the LS subprocess, manages JSON-RPC communication over stdin/stdout, dispatches responses/notifications to registered handlers.
- `ls_request.py` — `LanguageServerRequest`: synchronous wrapper that maps LSP method names (e.g. `textDocument/definition`) to typed Python methods.
- `ls_types.py` — Decoupled type definitions (`Position`, `Range`, `Location`, `UnifiedSymbolInformation`, `Hover`, `Diagnostic`, etc.) insulating consumers from upstream LSP type changes.
- `ls_utils.py` — `TextUtils` (line/col arithmetic), `PathUtils` (URI <-> path conversion), `FileUtils` (downloads, archive extraction, SHA256), `PlatformUtils` (OS/arch detection), `SymbolUtils`.
- `settings.py` — `SolidLSPSettings` dataclass: resource dirs, per-LS custom settings, cache storage mode (monolithic vs. per-file).

## Design Patterns
- **Abstract Base Class**: `SolidLanguageServer` defines the contract; each language (Python, Rust, Java, etc.) provides its own subclass via lazy imports in `Language.get_ls_class()`.
- **Factory**: `SolidLanguageServer.create()` dispatches to the correct subclass based on `LanguageServerConfig.code_language`.
- **Strategy**: `LanguageServerDependencyProvider` (and `SinglePath` variant) allows each LS to define how to obtain its executable.
- **Nested Request Classes**: `SymbolLocationRequest` (inner class) encapsulates the open-file -> send-request -> normalize-response flow, with concrete subclasses for definition/references/implementation.
- **Context Manager**: `open_file()` provides RAII-style file buffer lifecycle (didOpen/didClose notifications, ref-counting).

## Flow
1. Client creates a `SolidLanguageServer` via `create()` — subclass is selected by language, config is read, cache dirs are initialized.
2. `start()` launches the LS subprocess via `LanguageServerProcess`; background threads read stdout (JSON-RPC) and stderr (logging).
3. Before any LSP request, `open_file()` (context manager) sends `didOpen` notification and returns an `LSPFileBuffer`.
4. Symbol requests (definition, references, etc.) follow: open file -> send JSON-RPC request -> await response -> normalize to `ls_types.Location` list.
5. `stop()` performs graceful shutdown: LSP `shutdown` -> `exit` notification -> process terminate/kill with timeout.

## Integration
- Consumed by: `serena` application (higher-level indexing, code navigation)
- Depends on: `solidlsp.lsp_protocol_handler.*` (JSON-RPC / LSP protocol), `solidlsp.util.*` (caching, subprocess), `serena.util.*` (pickle, string, file system utils)
- Subdirectories: `language_servers/` (concrete LS implementations), `lsp_protocol_handler/` (protocol layer), `util/` (infrastructure)
