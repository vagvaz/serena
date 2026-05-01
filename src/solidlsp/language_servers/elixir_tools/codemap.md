# src/solidlsp/language_servers/elixir_tools/

## Responsibility
Wraps the **Expert** language server (official Elixir LSP) as a `SolidLanguageServer` subclass, enabling Elixir code navigation for the Serena analysis pipeline.

## Key Files
- `__init__.py` — Empty package init.
- `elixir_tools.py` — Contains `ElixirTools(SolidLanguageServer)`. Downloads the correct Expert binary per platform from GitHub releases, launches it with `--stdio`, triggers project compilation by opening `mix.exs`, waits up to 5 minutes for indexing, and normalises symbol names by stripping `def`/`defp` prefixes.

## Design Patterns
- **Binary auto‑download** — Platform‑specific `RuntimeDependency` objects with pinned SHA‑256 hashes fetch Expert from GitHub releases; falls back to `expert` in PATH if found.
- **Compilation‑driven readiness** — After the LSP handshake, opens `mix.exs` to trigger Expert's build pipeline, then waits for `$/progress` end signals (up to 300s) before considering the server ready.
- **Symbol normalisation** — Overrides `_normalize_symbol_name` to strip `def ` and `defp ` prefixes, and removes `(...)` argument lists.

## Flow
1. `_setup_runtime_dependencies()` checks for the `elixir` compiler, then downloads/populates the Expert binary for the current platform.
2. `__init__` passes a `ProcessLaunchInfo` with the binary path and `cwd`.
3. `_start_server()` registers handlers, starts the process, sends `initialize`/`initialized`, opens `mix.exs` to trigger compilation, and blocks until `$/progress` indicates the project build is done.
4. Once ready, the instance handles standard LSP requests for `.ex`/`.exs` files.

## Integration
- **Consumed by**: Resolved via `Language.ELIXIR.get_ls_class()` in `src/solidlsp/ls_config.py` → `ElixirTools`.
- **Depends on**: `common.py` (`RuntimeDependency`), `solidlsp.ls.SolidLanguageServer`, `solidlsp.ls_utils.FileUtils`/`PlatformUtils`.
