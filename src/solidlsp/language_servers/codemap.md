# src/solidlsp/language_servers/

## Responsibility
~45 Python modules, each wrapping a specific language server executable (pyright, gopls, rust-analyzer, zls, etc.) and registering it as a `SolidLanguageServer` subclass for use by the solidlsp framework.

## Key Files
- `common.py` — Shared base utilities: `RuntimeDependency`/`RuntimeDependencyCollection` dataclasses for binary download & npm install help; `build_npm_install_command()` helper.
- `*.py` (one per language) — Each module defines a `SolidLanguageServer` subclass that configures how to discover, install (if needed), launch, and initialize the external LSP binary.

## Design Patterns
- **Template Method** — `SolidLanguageServer` (in `ls.py`) defines the LSP lifecycle skeleton; each server overrides `_get_initialize_params`, `_start_server`, `_create_dependency_provider`, and `is_ignored_dirname`.
- **Two dependency models**: (a) *`ProcessLaunchInfo`* — servers assumed present in PATH (gopls, zls); (b) *`LanguageServerDependencyProvider`* — servers that may need auto-install via download or npm (clangd, typescript, bash). Inner `DependencyProvider` classes extend `LanguageServerDependencyProviderSinglePath`.
- **Event-based readiness** — Servers use `threading.Event` to wait for server-ready signals (e.g., `$/progress` end, `window/logMessage` analysis-complete, `experimental/serverStatus` quiescent).
- **Registry** — `Language.get_ls_class()` in `ls_config.py` uses a `match`/`case` statement mapping each `Language` enum value to its server class. To add a new language server: add a `Language` enum value, write the module here, add a `case` in `get_ls_class()`.

## Flow
1. `SolidLanguageServer.create()` reads the `Language` from config → calls `get_ls_class()` → instantiates the matching server class.
2. Constructor resolves the server binary (from PATH or by downloading/installing it).
3. `_start_server()` registers LSP notification/request handlers, spawns the binary process, sends `initialize` → `initialized`, and waits for readiness signals.
4. After startup, callers use the instance for LSP requests (hover, definition, references, document symbols, etc.).

## Integration
- **Consumed by**: `SolidLanguageServer.create()` in `src/solidlsp/ls.py`, which is called by higher‑level Serena analysis pipelines.
- **Depends on**: `common.py` utilities; `solidlsp.ls.SolidLanguageServer`, `solidlsp.ls_config.LanguageServerConfig`, `solidlsp.settings.SolidLSPSettings`, `solidlsp.lsp_protocol_handler`.
