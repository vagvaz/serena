# src/serena/

## Responsibility
The core `serena` Python package — an MCP (Model Context Protocol) agent toolkit. It implements the agent lifecycle, tool execution pipeline, project/session management, code intelligence backends (LSP/JetBrains), multi-client daemon mode, and a web dashboard.

## Key Files
- `agent.py` — `SerenaAgent`: top-level orchestrator holding all managers (Tool, Mode, Project, Session), owns startup/shutdown, tool exposure, and prompt generation. Also `DashboardManager` for display mode selection (browser/webview/tray).
- `cli.py` — Click-based CLI entry point (`serena` command). Defines all subcommands: `init`, `setup`, `start-mcp-server`, `daemon-status/stop`, `project`, `mode`, `context`, `config`, `tools`, `prompts` groups. Daemon subprocess spawn/management.
- `mcp.py` — `SerenaMCPFactory`: creates a `FastMCP` server backed by a `SerenaAgent`, converts Serena `Tool` instances to MCP tool descriptors (schema adaptation, docstring parsing, `cwd` parameter injection). Manages server lifespan with session registration.
- `tool_manager.py` — Three-phase tool lifecycle: `register_all()` (discovery via `ToolRegistry`), `compute_base()` (config/context/mode filtering), `compute_active()` (mode+project filtering). `ToolSet`, `AvailableTools`.
- `tool_schema.py` — `OpenAIToolSchemaAdapter`: transforms JSON Schema for OpenAI compatibility (`integer`→`number` with `multipleOf`, strips `null` from unions, simplifies `oneOf`/`anyOf`).
- `mode_manager.py` — `ActiveModes` (multi-source mode name set) and `ModeManager` (resolution pipeline: global config → project configs → session definition → dynamic overrides).
- `session_manager.py` — `SessionState` (per-client state: project binding, context/persona overrides, tool allowlist, timestamps) and `SessionManager` (thread-safe registry for multi-client daemon).
- `project_manager.py` — `ProjectManager`: zero-to-N active projects, path/session/name resolution (no ambiguous "get active"), language server lifecycle, idle timeout, disk persistence.
- `project.py` — `Project` (project identity, config, LS manager, filesystem delegation) and `MemoriesManager` (global + project-local `.md` memories with read-only/ignored patterns).
- `file_system.py` — `ProjectFileSystem`: file I/O, async `.gitignore`/config-based ignore matching (via `pathspec`), source file discovery, content search.
- `ls_manager.py` — `LanguageServerFactory` (creates `SolidLanguageServer` instances) and `LanguageServerManager` (parallel startup, per-file LS routing, restart, cache save).
- `code_editor.py` — `CodeEditor[TSymbol]` ABC with `LanguageServerCodeEditor` (LSP-backed) and `JetBrainsCodeEditor` implementations. File editing operations: replace/insert before-after symbol, delete lines/symbols, rename.
- `symbol.py` — `Symbol` ABC, `LanguageServerSymbol` (LSP symbol tree with name path matching, `NamePathMatcher`, `LanguageServerSymbolRetriever` for find/hover/references/overview), `JetBrainsSymbol`, `SymbolDictGrouper`.
- `task_executor.py` — `TaskExecutor`: thread-pool with per-project `ReadWriteLock`, sequential task ordering, task inspection/cancellation, read-only parallelism.
- `hooks.py` — Claude Code hook commands (`serena-hook` CLI). `PreToolUseRemindAboutSerenaHook` (denies excessive grep/read calls with token-bucket counter), `PreToolUseAutoApproveSerenaHook`, `SessionStartActivateProjectHook`, `SessionEndCleanupHook`.
- `dashboard.py` — `SerenaDashboardAPI` (Flask app: log streaming, tool stats, config overview, memories, news, task management), `SerenaDashboardViewer` (pywebview native window), `SerenaDashboardTrayManager` (multi-instance system tray), `ReadNews`.
- `gui_log_viewer.py` — Tkinter-based log viewer (`GuiLogViewer`) with colored levels and tool name highlighting, `GuiLogViewerHandler` (logging handler), `show_fatal_exception()`.
- `analytics.py` — Token counting strategies (`TiktokenCountEstimator`, `AnthropicTokenCount`, `CharCountEstimator`) via `RegisteredTokenCountEstimator` enum. `ToolUsageStats` for per-tool call/token recording.
- `project_server.py` — `ProjectServer` (Flask HTTP server exposing read-only tool queries on demand-loaded projects) and `ProjectServerClient`.
- `agno.py` — Agno AI integration: `SerenaAgnoToolkit` (wraps tools as Agno `Function`s) and `SerenaAgnoAgentProvider` (singleton `Agent` factory).
- `prompt_factory.py` — `SerenaPromptFactory`: renders prompt templates from user and internal template directories (extends generated `PromptFactory`).
- `constants.py` — Path constants (`REPO_ROOT`, `SERENA_DASHBOARD_DIR`, template paths), `SerenaPorts`, `DEFAULT_CONTEXT`, `SERENA_LOG_FORMAT`.
- `__init__.py` — Package version (`1.2.0`), `serena_version()` with git status, log configuration.

## Design Patterns
- **Orchestrator + Managers**: `SerenaAgent` delegates to specialized managers (ToolManager, ModeManager, ProjectManager, SessionManager) — each with single responsibility.
- **Three-phase lifecycle**: Tool filtering (register → compute_base → compute_active), Mode resolution (config → project → session → override).
- **Strategy/Backend**: `CodeEditor` abstracted over LSP vs JetBrains; `TokenCountEstimator` over tiktoken/Anthropic/char-count.
- **Per-project read-write locking**: `TaskExecutor` allows concurrent read-only tool calls on the same project, serializes writes.
- **Thread-safe state**: All managers use `threading.Lock`; session state is immutable-copy on read.
- **Background initialization**: Ignore spec gathering, language server startup, news fetching, dashboard all start async.
- **Hook pipeline (Claude Code)**: stdin-read → class dispatch → stdout JSON with permission decisions.

## Flow
1. **Entry**: `cli.py` → `start-mcp-server` → `SerenaMCPFactory.create_mcp_server()` → `SerenaAgent()` init + `FastMCP` wrapping.
2. **Agent init**: Loads config → registers all tools (`ToolManager.register_all`) → activates startup project → computes exposed tool set → starts dashboard.
3. **MCP connection**: `server_lifespan` → registers session in `SessionManager` → maps Serena tools to MCP tool descriptors (with `cwd` parameter) → yields.
4. **Tool call**: MCP executes `execute_fn(**kwargs)` → `Tool.apply_ex()` → resolves project via `ProjectManager.resolve_for_session(cwd, session_id)` → runs in `TaskExecutor` (per-project locking) → records analytics.
5. **Project changes**: `_on_projects_changed` callback atomically refreshes modes and tools via `_refresh_active_state()`.
6. **Daemon mode**: CLI spawns background subprocess with SSE transport. Multiple clients connect, each gets its own session. Idle checker shuts down unused projects.
7. **Dashboard**: Flask API reads live state (logs, tool stats, config, sessions, memories, news). Viewer runs as pywebview window or tray manager.
8. **CLI hooks**: `serena-hook` commands read JSON from stdin, execute hook logic, emit JSON to stdout (used by Claude Code's hook system).

## Integration
- **Consumed by**: MCP clients (Claude Desktop, Claude Code, VS Code via MCP, OpenCode, Cline), Agno UI, JetBrains plugin (via HTTP), project server clients.
- **Depends on**: `solidlsp` (LSP client), `mcp` (FastMCP SDK), `agno` (optional AI framework), `click` (CLI), `flask` (dashboard), `pywebview`/`pystray` (native UI), `pathspec` (gitignore), `tiktoken`/`anthropic` (token counting), `jinja2`/`interprompt` (prompt templates).
