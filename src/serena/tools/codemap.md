# src/serena/tools/

## Responsibility
Implements all MCP tools exposed to the LLM client, organised by domain: file operations, symbol/code intelligence, memory management, configuration, JetBrains integration, cross-project queries, workflow, and session management.

## Key Files
- `tools_base.py` — Framework: `Component` (injects agent/project), `Tool` (apply + apply_ex with logging, timeout, project context, error handling), `ToolRegistry` (singleton auto-discovers tools by subclass), tool markers (`ToolMarkerCanEdit`, `ToolMarkerOptional`, `ToolMarkerSymbolicRead`, etc.), `EditedFileContext`, `project_context` contextvar
- `file_tools.py` — File tools: `Read`, `CreateTextFile`, `ListDir`, `FindFile`, `ReplaceContent`, `DeleteLines`, `ReplaceLines`, `InsertAtLine`, `SearchForPattern`
- `symbol_tools.py` — LSP symbol tools: `FindSymbol`, `GetSymbolsOverview`, `FindReferencingSymbols`, `ReplaceSymbolBody`, `InsertAfterSymbol`, `InsertBeforeSymbol`, `RenameSymbol`, `SafeDeleteSymbol`, `RestartLanguageServer`
- `memory_tools.py` — Memory tools: `WriteMemory`, `ReadMemory`, `ListMemories`, `DeleteMemory`, `RenameMemory`, `EditMemory`
- `cmd_tools.py` — `ExecuteShellCommand` tool
- `config_tools.py` — Config/management tools: `OpenDashboard`, `RestartDashboard`, `ActivateProject`, `SetSessionProject`, `DeactivateProject`, `ListActiveProjects`, `GetProjectStatus`, `RemoveProject`, `GetCurrentConfig`
- `jetbrains_tools.py` — JetBrains-specific tools: `JetBrainsFindSymbol`, `JetBrainsMove`, `JetBrainsSafeDelete`, `JetBrainsInline`, `JetBrainsRename`, `JetBrainsFindReferencingSymbols`, `JetBrainsGetSymbolsOverview`, `JetBrainsTypeHierarchy`, `JetBrainsFindDeclaration`, `JetBrainsFindImplementations`, `JetBrainsDebug`
- `query_project_tools.py` — `ListQueryableProjects`, `QueryProject` (execute read-only tools in other projects)
- `session_tools.py` — `SessionInit` (per-session config for daemon clients)
- `workflow_tools.py` — Workflow tools: `CheckOnboardingPerformed`, `Onboarding`, `InitialInstructions`
- `__init__.py` — Re-exports all tool classes

## Design Patterns
- **Template Method**: `Tool.apply_ex` wraps every `apply()` call with project resolution, session binding, logging, error handling, timeouts, and LSP cache saving
- **Marker classes**: `ToolMarkerCanEdit`, `ToolMarkerOptional`, `ToolMarkerSymbolicRead`, `ToolMarkerSymbolicEdit`, etc. provide trait-like classification used by the tool registry and LLM prompt generation
- **Singleton**: `ToolRegistry` auto-discovers all `Tool` subclasses at import time via `iter_subclasses`
- **Context variable**: `_current_project` (ContextVar) scopes the active project per tool execution, enabling safe concurrent session handling
- **Result shortening**: `_limit_length` with progressive shortening closures — tries increasingly compact representations when the answer exceeds `max_answer_chars`
- **Tool grouping**: `LanguageServerSymbolDictGrouper` / `JetBrainsSymbolDictGrouper` collapse symbol result lists into compact file/type-grouped JSON

## Flow
1. MCP server receives tool call → resolves project via `resolve_session_project` → sets `_current_project` ContextVar → calls `tool.apply_ex()`
2. `apply_ex` validates tool is active, checks session allowlist, extracts client info from MCP context, issues the task to the agent's task executor with timeout
3. Inside `apply()`: the tool reads/writes files, queries LSP/JetBrains, or accesses memory, then returns a string result
4. `_limit_length` optionally shortens the result if it exceeds `max_answer_chars`

## Integration
- Consumed by: MCP server (via `serena.agent`), which registers tools with the FastMCP framework
- Depends on: `serena.config`, `serena.jetbrains`, `serena.project`, `serena.project_server`, `serena.code_editor`, `serena.symbol`, `serena.session_manager`, `serena.util`, `solidlsp`
