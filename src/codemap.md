# src/

## Responsibility
Root of all source code in the Serena project. Contains the main agent/MCP toolkit (`serena`) along with two vendored/adapted sub-packages: a synchronous LSP framework (`solidlsp`) and a Jinja2-based prompt generation system (`interprompt`).

## Directory Structure
| Directory | Responsibility |
|-----------|---------------|
| `serena/` | Core agent orchestration, MCP server, tool system, session/project management, CLI, and GUI dashboard. |
| `solidlsp/` | Fully synchronous Language Server Protocol framework (fork of `microsoft/multilspy`). |
| `interprompt/` | Multi-language prompt generation library built on Jinja2 templates. |
| `README.md` | Documents that `solidlsp` and `interprompt` are modified third-party packages. |

## Design Patterns
- **Layered isolation** — each sub-package is self-contained with minimal cross-dependency.
- **Modified vendoring** — `solidlsp` and `interprompt` are adapted forks of upstream libraries, kept as inline packages for tight integration.
- **Module-level separation** — `serena/` organises features into distinct modules (agent, tools, MCP, session, project, CLI, analytics) rather than a deep nesting of sub-packages.

## Integration
- **Consumed by:** `serena/` is the primary consumer of `solidlsp/` (language server automation) and `interprompt/` (prompt generation).
- **Depends on:** `solidlsp/` ↔ language server binaries (node, platform LSP servers); `interprompt/` ↔ Jinja2 templates bundled under its `util/` or external paths.
