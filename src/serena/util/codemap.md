# src/serena/util/

## Responsibility
Provides general-purpose utility modules used across the Serena codebase, covering filesystem operations, logging, CLI, YAML, text search, threading, versioning, and more.

## Key Files
- `shell.py` — Wraps `subprocess.Popen` and `check_output` for executing shell commands
- `file_system.py` — Directory scanning and `.gitignore`-aware path filtering via `GitignoreParser`
- `logging.py` — In-memory log buffer (`MemoryLogHandler`), `StopWatch`, `LogTime` context manager, session-scoped log context
- `text_utils.py` — Regex/glob text search (`search_text`, `search_files`), content replacement (`ContentReplacer`), HTML-to-text rendering
- `yaml.py` — Comment-preserving YAML load/save via `ruamel.yaml`, with comment normalisation strategies
- `string_utils.py` — `ToStringMixin` base class, `TextBuilder`, `dict_string`
- `thread.py` — `execute_with_timeout` — runs a callable in a daemon thread with a timeout
- `git.py` — `GitStatus` dataclass and `get_git_status` using `git rev-parse`/`diff`/`ls-files`
- `dotnet.py` — .NET runtime version detection and installation via Microsoft scripts
- `version.py` — Numeric version comparison (`is_at_least`, `is_at_most`, `is_equal`)
- `pickle_utils.py` — Pickle with optional bz2 compression and `getstate` helper for `__getstate__` implementations
- `cli_util.py` — `AutoRegisteringGroup` (auto-discovers `click.Command` attributes) and `ask_yes_no`
- `inspection.py` — `iter_subclasses` and `determine_programming_language_composition` (file-count-based)
- `pywebview.py` — `WebViewWithTray` — pywebview window with system tray, parent-process monitoring, macOS-specific lifecycle helpers
- `gui.py` — Platform-aware display availability detection
- `exception.py` — Headless environment detection and safe fatal-exception display
- `class_decorators.py` — `@singleton` decorator
- `dataclass.py` — `get_dataclass_default` helper
- `misc.py` — `mark_used` to suppress linter warnings

## Design Patterns
- **Utility functions** with no or minimal state (most modules are collections of standalone functions)
- **Context managers** extensively used for setup/teardown (`LogTime`, `SuspendedLoggersContext`, `FileLoggerContext`)
- **Thread-safe buffer** (`LogBuffer` with lock) for the in-memory logging pipeline
- **Strategy pattern** in `YamlCommentNormalisation` for comment handling modes
- **Singleton** (`class_decorators.py`) for registry-like components

## Flow
- Consumers import specific utilities as needed; no central dispatch.
- Logging flows: application code → `logging.getLogger` → `MemoryLogHandler` (background thread → `LogBuffer`) → polled by dashboard or other consumers via `get_log_messages`.
- YAML load: `load_yaml` → `ruamel` parse → optional comment normalisation → `CommentedMap` returned.

## Integration
- Consumed by: All other `serena.*` packages (`config`, `tools`, `jetbrains`, `agent`, etc.)
- Depends on: `psutil`, `PIL`, `ruamel.yaml`, `pathspec`, `beautifulsoup4`, `joblib`, `pywebview`, `pystray`, `click`, `solidlsp`
