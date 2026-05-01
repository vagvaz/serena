# test/serena/

## Responsibility
Integration and unit tests for the `serena` package — the main application layer including agents, tools, sessions, MCP, hooks, CLI commands, configuration, and utilities.

## Key Files
- **`__init__.py`**: Empty package marker.
- **Subdirectory `config/`**: Tests for `SerenaConfig`, `ProjectConfig`, global ignored paths, and configuration file loading.
- **Subdirectory `util/`**: Tests for `GitignoreParser`, headless environment detection, and exception handling.
- **`test_serena_agent.py`**: Comprehensive tests for `SerenaAgent` — project activation, tool execution, multi-language support (798 lines).
- **`test_session_manager.py`**: Tests for `SessionManager` and `SessionState` dataclass (session lifecycle, idle tracking, dict serialization).
- **`test_session_agent.py`**: Tests for session-aware agent behavior.
- **`test_mcp.py`**: Tests for MCP tool conversion via `SerenaMCPFactory.make_mcp_tool`.
- **`test_tool_manager.py`**: Tests for `ToolRegistry` and tool lifecycle management.
- **`test_tool_schema.py`**: Tests for tool schema generation.
- **`test_tool_parameter_types.py`**: Tests for parameter type handling in tools.
- **`test_task_executor.py`**: Tests for task execution pipeline.
- **`test_hooks.py`**: Tests for hook system — `PreToolUseRemindAboutSerenaHook`, `SessionEndCleanupHook`, `PreToolUseAutoApproveSerenaHook`.
- **`test_symbol.py`**: Tests for `NamePathMatcher`, `LanguageServerSymbol`, and name path matching logic.
- **`test_symbol_editing.py`**: Tests for symbol-level edit operations.
- **`test_text_utils.py`**: Tests for `search_text`, `search_files`, line range retrieval, and content extraction.
- **`test_mode_manager.py`**: Tests for mode resolution pipeline (`ActiveModes`, `ModeManager`).
- **`test_cli_project_commands.py`**: Tests for CLI `project create` and `project index` commands using Click's `CliRunner`.
- **`test_dashboard.py`**: Tests for web dashboard functionality.
- **`test_jetbrains_plugin_client.py`**: Tests for JetBrains IDE plugin client communication.
- **`test_edit_marker.py`**: Tests for edit marker parsing and application.

## Design Patterns
- **Class-based test organization**: Test classes group related functionality (e.g., `TestProjectConfigAutogenerate`, `TestEffectiveLanguageBackend`).
- **Temporary directory fixtures**: Tests use `tempfile.mkdtemp()` with `setup_method`/`teardown_method` for isolated filesystem testing.
- **Mocking**: `unittest.mock` used extensively for headless detection tests, external service calls, and environment simulation.
- **CLI testing**: `click.testing.CliRunner` used for command-line interface tests.
- **Snapshot testing**: Snapshot files in `__snapshots__/` for deterministic output comparison.

## Flow
```
pytest discovers tests in test/serena/
  ├── Config tests       → SerenaConfig, ProjectConfig autogeneration, ignored_paths
  ├── Agent tests        → SerenaAgent lifecycle, project activation, tool dispatch
  ├── Session tests      → SessionManager, SessionState, multi-client daemon mode
  ├── MCP tests          → MCP tool conversion, parameter handling
  ├── Hook tests         → PreToolUseRemind, SessionEndCleanup, AutoApprove
  ├── Symbol tests       → NamePathMatcher, LanguageServerSymbol retrieval
  ├── CLI tests          → Click commands via CliRunner
  └── Util tests         → GitignoreParser, headless detection, exception dialogs
```

## Integration
- Depends on `test/conftest.py` for language server fixtures (`language_server`, `project`) and resource paths.
- Uses the `serena` package internally (agents, config, project, tools, sessions).
- Some tests (e.g., `TestEffectiveLanguageBackend`) may start real language server processes.
