# Repository Atlas: Serena

## Project Responsibility
A powerful MCP (Model Context Protocol) toolkit that provides semantic code retrieval and editing capabilities via LLM agents. Serves as an AI coding IDE that integrates with Claude Desktop, Claude Code, VS Code, OpenCode, Cline, and JetBrains IDEs through MCP protocol.

## System Entry Points
- `pyproject.toml` — Project configuration: dependencies, build system, tasks (test/lint/type-check/docs).
- `src/serena/cli.py` — CLI entry point (`serena` command) for MCP server, project management, and daemon mode.
- `scripts/mcp_server.py` — Thin MCP server startup entry point.

## Directory Map (Aggregated)

| Directory | Responsibility Summary | Detailed Map |
|-----------|------------------------|--------------|
| `src/` | Root of all source code (serena + solidlsp + interprompt packages) | [View Map](src/codemap.md) |
| `src/serena/` | Core agent orchestration, MCP server, tool system, session/project management, CLI, dashboard | [View Map](src/serena/codemap.md) |
| `src/serena/util/` | General-purpose utilities: filesystem, logging, YAML, text search, CLI, threading, versioning | [View Map](src/serena/util/codemap.md) |
| `src/serena/config/` | Configuration system: global serena_config.yml, project.yml, context/mode definitions, client setup | [View Map](src/serena/config/codemap.md) |
| `src/serena/tools/` | All MCP tools exposed to LLM clients: file ops, symbols, memory, config, JetBrains, sessions, workflow | [View Map](src/serena/tools/codemap.md) |
| `src/serena/jetbrains/` | HTTP client and types for JetBrains IDE plugin API | [View Map](src/serena/jetbrains/codemap.md) |
| `src/serena/generated/` | Auto-generated typed prompt factory from prompt templates | [View Map](src/serena/generated/codemap.md) |
| `src/solidlsp/` | Synchronous LSP framework: server lifecycle, file buffers, symbol caching (fork of multilspy) | [View Map](src/solidlsp/codemap.md) |
| `src/solidlsp/language_servers/` | ~45 Python modules wrapping specific language server executables (pyright, gopls, rust-analyzer, etc.) | [View Map](src/solidlsp/language_servers/codemap.md) |
| `src/solidlsp/lsp_protocol_handler/` | JSON-RPC 2.0 / LSP v3.17.0 protocol layer: serialization, typed requests, type definitions | [View Map](src/solidlsp/lsp_protocol_handler/codemap.md) |
| `src/solidlsp/util/` | LSP utilities: symbol cache persistence, Metals lock management, subprocess helpers, ZIP extraction | [View Map](src/solidlsp/util/codemap.md) |
| `src/interprompt/` | Jinja2-based prompt templating with multi-language support and code generation | [View Map](src/interprompt/codemap.md) |
| `src/interprompt/util/` | Singleton decorator utility for interprompt | [View Map](src/interprompt/util/codemap.md) |
| `scripts/` | Utility and demo scripts: version bump, news build, code generation, profiling, diagnostics | [View Map](scripts/codemap.md) |
| `test/` | Integration test suite for serena and solidlsp packages | [View Map](test/codemap.md) |
| `test/serena/` | Tests for serena: agents, sessions, MCP, hooks, CLI, symbols, tools, config, utilities | [View Map](test/serena/codemap.md) |
| `test/solidlsp/` | LSP integration tests: document symbols, references, definitions across 50+ language servers | [View Map](test/solidlsp/codemap.md) |

## Design Patterns
- **Orchestrator + Managers**: `SerenaAgent` delegates to specialized managers (Tool, Mode, Project, Session) with single responsibility
- **Three-phase tool lifecycle**: register → compute_base (config/context/mode) → compute_active (session/project filtering)
- **Strategy/Backend abstraction**: `CodeEditor` over LSP vs JetBrains; pluggable token counting; monolithic vs per-file cache
- **Modified vendoring**: `solidlsp` and `interprompt` are adapted forks kept as inline packages for tight integration
- **Per-project read-write locking**: concurrent read-only tool calls, serialized writes
- **Layered isolation**: each sub-package is self-contained with minimal cross-dependency
- **Environment-gated tests**: 50+ language server tests auto-skip when binary is unavailable

## Data Flow
```
CLI (cli.py) → MCP Server (mcp.py) → SerenaAgent (agent.py)
  ├── Tool lifecycle (tool_manager.py → tools/*.py)
  ├── LSP backend (ls_manager.py → solidlsp/ → language_servers/*.py)
  ├── JetBrains backend (jetbrains/ → HTTP to IDE plugin)
  ├── Project management (project.py, project_manager.py)
  ├── Session management (session_manager.py)
  └── Dashboard (dashboard.py) ← Flask + pywebview/pystray
```
