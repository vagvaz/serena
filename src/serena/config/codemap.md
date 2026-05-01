# src/serena/config/

## Responsibility
Manages the Serena configuration system — global `serena_config.yml`, per-project `project.yml`/`project.local.yml`, context and mode definitions, and client onboarding/setup.

## Key Files
- `serena_config.py` — Core configuration: `SerenaConfig` (global), `ProjectConfig` (per-project), `RegisteredProject`, `SerenaPaths` (singleton for directory layout), `LanguageBackend` enum (LSP vs JetBrains), `LineEnding` enum, `ToolInclusionDefinition` and `ModeSelectionDefinition` base classes
- `context_mode.py` — `SerenaAgentMode` and `SerenaAgentContext` dataclasses loaded from YAML, defining tool visibility and system-prompt templates per context/mode
- `client_setup.py` — `ClientSetupHandler` ABC with concrete handlers for Claude Code (`ClientSetupHandlerClaudeCode`) and Codex CLI (`ClientSetupHandlerCodex`), providing MCP server registration commands

## Design Patterns
- **Singleton** (`SerenaPaths` via `@singleton`) for global path resolution
- **Dataclass composition**: `SharedConfig` → `SerenaConfig` (global) and `ProjectConfig` (per-project) share fields; `ModeSelectionDefinition` base classes compose with tool inclusion logic
- **YAML-backed configuration** with comment-preserving load/save, template-based defaults, and migration of legacy fields
- **Backward-compatibility layer**: legacy field renaming (`jetbrains` → `language_backend`, `gui_log_level` → `log_level`, project file migration to `.serena/project.yml`)
- **Registry pattern**: `client_setup_handlers` list at module level for auto-discovery

## Flow
1. `SerenaConfig.from_config_file()` → resolves `serena_config.yml` (auto-generates from template if missing) → loads global settings + registered projects and their `project.yml`
2. `ProjectConfig.load()` → merges `project.yml` with `project.local.yml` overrides → auto-generates if `autogenerate=True` by detecting languages via file counts
3. `SerenaAgentMode.from_name()` / `SerenaAgentContext.from_name()` → looks up `<name>.yml` in user dirs first, then built-in dirs → returns dataclass with prompt template and tool filters
4. `ClientSetupHandler.apply()` → runs shell commands to register the MCP server with the respective client

## Integration
- Consumed by: `serena.agent`, `serena.project`, `serena.tools`, `serena.tools.config_tools`, CLI entry points
- Depends on: `serena.util` (file_system, logging, class_decorators, inspection, cli_util, yaml, string_utils, shell), `solidlsp.ls_config`, `ruamel.yaml`
