# Multi-Project Support Implementation Plan

## Overview
Transform Serena from single-project to multi-project architecture, enabling concurrent project handling with session-based caching, lazy LSP loading, idle timeout, and persistence.

## Design Principles
- `dict[str, Project]` keyed by project name (not set, since Project uses identity-based hash)
- Session-based project caching (per MCP client connection)
- `contextvars` for project context (not thread-locals)
- Lazy LSP loading with configurable idle shutdown
- Per-project persistence to `.serena/active_state.json`
- Backward compatible: `cwd` parameter is optional

## Architecture Flow
```
Client tool call (cwd="/path/to/project/src")
    ↓
MCP: extract session_id, pass cwd to apply_ex
    ↓
apply_ex: resolve_session_project(session_id, cwd)
    → check cwd → find matching project root
    → cache project_name in _session_projects[session_id]
    ↓
_apply_with_project(project):
    → set contextvar _current_project = project
    → inject project=project into kwargs if apply_fn accepts it
    → call apply_fn(**kwargs)
    → reset contextvar
    ↓
Tool executes with correct project context
    ↓
_touch_project(project) → update last_active timestamp
```

## Implementation Phases (each = one commit)

### Phase 1: Core Data Structure
**Commit**: `feat: replace _active_project with _active_projects dict`
- `agent.py`: `_active_project: Project | None` → `_active_projects: dict[str, Project]`
- Add `_session_projects: dict[str, str]` (session_id → project_name)
- Update `get_active_project()` to return first active project (backward compat)
- Add `get_active_project_by_name(name)` method
- Add `get_all_active_projects()` method
- Update `_activate_project()` → `_add_active_project()` (no shutdown)
- Add `_remove_active_project()` method
- Update `active_project_context()` to work with new structure

### Phase 2: Path Resolution
**Commit**: `feat: add path-to-project resolution with longest-prefix matching`
- Add `resolve_project_for_path(cwd: str) -> Project | None`
- Add `_project_root_index` property (cached mapping of root → Project)
- Handle nested projects (longest prefix wins)
- Add unit tests for path resolution

### Phase 3: Session-Based Project Caching
**Commit**: `feat: add session-based project caching`
- Add `resolve_session_project(session_id, cwd) -> Project | None`
- Cache resolved project per session in `_session_projects`
- Extract session_id from MCP context
- Add `get_session_project(session_id)` method

### Phase 4: Contextvars Project Context
**Commit**: `feat: replace thread-local with contextvars for project context`
- Add `_current_project: ContextVar[Project | None]` in `tools_base.py`
- Add `project_context(project)` context manager using contextvars
- Update `Component.project` property to use contextvars
- Remove any thread-local patterns

### Phase 5: Tool Wrapper with cwd Parameter
**Commit**: `feat: add cwd parameter to tool execution with project resolution`
- Update `Tool.apply_ex()` to accept `cwd: str | None = None`
- Add `_apply_with_project()` wrapper that:
  - Resolves project from session/cwd
  - Sets contextvar
  - Injects `project` kwarg if apply_fn accepts it
  - Resets contextvar after execution
- Update `Component.project` to use contextvars fallback
- Touch project on successful execution

### Phase 6: Lazy LSP + No Shutdown on Switch
**Commit**: `feat: remove shutdown-on-switch, enable lazy LSP loading`
- Remove `project.shutdown()` call from `_add_active_project()`
- Ensure LSPs are lazily started (already lazy via `RegisteredProject`)
- Add explicit `deactivate_project()` for manual shutdown
- Update `ActivateProjectTool` to add to active set instead of replacing

### Phase 7: Idle Timeout Checker
**Commit**: `feat: add configurable idle timeout with periodic checker`
- Add `_project_last_active: dict[str, float]` tracking
- Add `_touch_project(project)` method
- Add `_check_idle_projects()` periodic checker
- Default: 30 min timeout, 5 min check interval
- Both configurable via `serena_config`
- Add `project_idle_timeout_seconds` and `project_idle_check_interval_seconds` to config

### Phase 8: Per-Project Persistence
**Commit**: `feat: add per-project state persistence and restoration`
- Add `_persist_project_state(project)` → `.serena/active_state.json`
- Add `_persist_all_projects()` for bulk save
- Add `_restore_projects_from_disk()` on agent startup
- Persistence triggers:
  - Idle check (every 5 min)
  - New project activated
  - Project deactivated/shutdown
  - Agent shutdown

### Phase 9: New MCP Tools
**Commit**: `feat: add DeactivateProjectTool, ListActiveProjectsTool, GetProjectStatusTool`
- `DeactivateProjectTool`: shutdown and remove project from active set
- `ListActiveProjectsTool`: list all active projects with status
- `GetProjectStatusTool`: detailed status of specific project
- All marked `ToolMarkerDoesNotRequireActiveProject`

### Phase 10: Update All Tools with cwd Parameter
**Commit**: `feat: add cwd parameter to all tool apply() methods`
- Add `cwd: str | None = None` as first optional param to all `apply()` methods
- Add `project: Project | None = None` where tools need explicit project access
- Use fixer agent for bulk updates across tool files

### Phase 11: MCP Session Sharing
**Commit**: `feat: share SerenaAgent instance across MCP connections`
- Update `SerenaMCPFactory` to reuse agent instance
- Agent survives client disconnects/reconnects
- Only shutdown on explicit command or process exit

### Phase 12: Dashboard Updates
**Commit**: `feat: update dashboard to show multiple active projects`
- Replace single `project_info` with `active_projects: list[dict]`
- Show each project's: name, path, languages, LSP status, idle time
- Add "registered but not active" section
- Remove "start from scratch" behavior

### Phase 13: Config Updates & Cleanup
**Commit**: `feat: add multi-project config fields and cleanup`
- Add `project_idle_timeout_seconds` to `SerenaConfig`
- Add `project_idle_check_interval_seconds` to `SerenaConfig`
- Update `single_project` context mode behavior
- Update `project_server.py` for multi-project agent
- Final cleanup and documentation

## Key Files to Modify
| File | Phases |
|------|--------|
| `src/serena/agent.py` | 1, 2, 3, 6, 7, 8, 11 |
| `src/serena/tools/tools_base.py` | 4, 5, 10 |
| `src/serena/tools/config_tools.py` | 6, 9 |
| `src/serena/tools/*.py` | 10 |
| `src/serena/mcp.py` | 11 |
| `src/serena/dashboard.py` | 12 |
| `src/serena/config/serena_config.py` | 7, 13 |
| `src/serena/project_server.py` | 13 |

## Dependencies Between Phases
- Phase 1 → Phase 2, 3, 6 (core structure needed first)
- Phase 2 → Phase 3 (path resolution needed for session caching)
- Phase 3 → Phase 5 (session caching needed for tool wrapper)
- Phase 4 → Phase 5 (contextvars needed for wrapper)
- Phase 5 → Phase 10 (wrapper pattern established before bulk tool updates)
- Phase 6 → Phase 7 (no shutdown needed before idle checker)
- Phase 7 → Phase 8 (idle checker needed before persistence)
- Phase 9, 11, 12 can be done in parallel after Phase 1
- Phase 13 is final cleanup

## Parallel Execution Strategy
- **Batch 1**: Phase 1 (foundation)
- **Batch 2**: Phases 2, 3, 4, 6 (independent after Phase 1)
- **Batch 3**: Phases 5, 7 (depend on Batch 2)
- **Batch 4**: Phases 8, 9, 11, 12 (can be parallelized)
- **Batch 5**: Phase 10 (bulk tool updates, can use fixer)
- **Batch 6**: Phase 13 (final cleanup)
