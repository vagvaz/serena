# src/serena/jetbrains/

## Responsibility
Provides the HTTP client and type definitions for communicating with the Serena JetBrains IDE plugin, enabling symbol queries, refactoring, and debugging through the IDE's language intelligence.

## Key Files
- `jetbrains_plugin_client.py` — HTTP client (`JetBrainsPluginClient`) and manager (`JetBrainsPluginClientManager`) for the JetBrains plugin's REST API. Handles port scanning, path matching (including WSL UNC paths), symbol queries, refactoring operations, and debug REPL
- `jetbrains_types.py` — `TypedDict` definitions for the JetBrains API: `SymbolDTO`, `SymbolCollectionResponse`, `GetSymbolsOverviewResponse`, `TypeHierarchyNodeDTO`, `TypeHierarchyResponse`, `PluginStatusDTO`, `PositionDTO`, `TextRangeDTO`

## Design Patterns
- **Singleton** (`JetBrainsPluginClientManager`) — caches discovered plugin clients and manages port scanning
- **Context manager** (`JetBrainsPluginClient.__enter__/__exit__`) — ensures HTTP session is closed after use
- **Port scanning** — scans a range of BASE_PORT..BASE_PORT+19 in parallel using `ThreadPoolExecutor` to find running plugin instances
- **Path matching** — accounts for WSL UNC paths (`//wsl.localhost/...`), `/mnt/c/` prefixes, and case-insensitive suffix matching
- **CamelCase to snake_case conversion** (`_pythonify_response`) — recursively converts API response keys
- **Version gating** (`_require_version_at_least`) — ensures the plugin version supports the requested operation

## Flow
1. `JetBrainsPluginClient.from_project()` → tries cached port, then delegates to `JetBrainsPluginClientManager.find_client()` → parallel port scan → connects to first matching plugin instance → returns client
2. Tool calls e.g. `client.find_symbol(name_path, ...)` → POSTs JSON to plugin HTTP endpoint → receives camelCase response → converts to snake_case → post-processes HTML documentation → returns TypedDict
3. `match_clients()` matches all registered projects against running plugin instances for cross-project queries

## Integration
- Consumed by: `serena.tools.jetbrains_tools`, `serena.tools.query_project_tools`, `serena.code_editor`, `serena.symbol.jetbrains`
- Depends on: `requests`, `serena.util` (class_decorators, text_utils, version, string_utils), `serena.config.serena_config`, `serena.constants`, `serena.project`
