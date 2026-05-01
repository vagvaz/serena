# scripts/

## Responsibility
Utility and demo scripts for the Serena project — version management, news data builds, code generation, profiling, and tool/diagnostics exploration. Not part of the main runtime.

## Key Files
- `bump_version.py` — Click CLI that bumps the project version in `pyproject.toml`, `__init__.py`, and `CHANGELOG.md`, then commits and tags.
- `build_news_json.py` — Aggregates individual HTML news files into a single `news.json` and optionally SCPs it to a remote server.
- `gen_prompt_factory.py` — Auto-generates `generated_prompt_factory.py` from prompt template files via `interprompt`.
- `mcp_server.py` — Entry point that starts Serena's MCP server (`top_level.start_mcp_server()`).
- `demo_cli_call.py` — Minimal smoke test that invokes `top_level(["--help"])`.
- `demo_run_tools.py` — Interactive demo that exercises JetBrains/LSP tools (find symbol, refs, overview, etc.) against the Serena repo itself.
- `demo_progressive_tool_shortening.py` — Exercises `_limit_length` shortening stages across LSP and JetBrains backends to verify progressive truncation.
- `profile_tool_call.py` — Profiles a single `FindSymbolTool` call with `cProfile` or `pyinstrument`.
- `agno_agent.py` — Boots Serena inside an Agno AgentOS app (wraps `SerenaAgnoAgentProvider`).
- `print_tool_overview.py` — Prints all registered tools via `ToolRegistry().print_tool_overview()`.
- `print_mode_context_options.py` — Prints registered agent modes and contexts via `SerenaAgentMode`/`SerenaAgentContext`.
- `print_language_list.py` — Prints supported language enum values for use in `project.yml` templates.

## Design Patterns
- **Self-hosting demos**: Demo scripts operate on Serena's own repo to keep test data readily available.
- **Thin entry points**: `mcp_server.py` and `demo_cli_call.py` are single-expression modules that delegate entirely to `serena.cli`.
- **Configuration re-use**: All scripts that need an agent create it via `SerenaConfig.from_config_file()`, inheriting the user's existing settings.
- **Standalone CLI**: `bump_version.py` is a self-contained Click command with dry-run support and full validation.

## Flow
1. **Diagnostics** (`print_*`) → import serena types, enumerate/call them, print to stdout.
2. **Demos** (`demo_*`) → instantiate `SerenaAgent` with the local config, retrieve tool instances, invoke `agent.execute_task()` with lambdas.
3. **Build/Release** (`build_news_json.py`, `bump_version.py`) → read files from disk, transform, write back (and optionally git-commit or scp).
4. **Profiling** (`profile_tool_call.py`) → set up agent, call function under profiler, output `.pstat` or log.

## Integration
- Consumed by: Developers running ad-hoc diagnostics, CI/release automation, Agno AgentOS deployments.
- Depends on: `serena.agent`, `serena.cli`, `serena.config`, `serena.tools`, `serena.constants`, `solidlsp`, `interprompt`, `agno`, `sensai`.
