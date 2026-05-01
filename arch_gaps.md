# Architecture Deepening Opportunities

Analysis date: 2026-05-01  
Context: Post-merge of multi-project branch into main (mode revamp integrated).  
Method: Parallel exploration of agent, tools, LSP, and CLI modules.

---

## Candidate 1 — Extract `ToolManager` from SerenaAgent

**Files:** `agent.py` (~1,610 lines, ~45 public methods)  
**Scope:** Tool lifecycles distributed across agent.py

### Problem

SerenaAgent is a god class — 1,610 lines, ~45 public methods, depends on everything. Tool lifecycle is split across three distinct phases embedded in the agent:

| Phase | Location in agent.py | What it does |
|-------|---------------------|--------------|
| Registration | `__init__` (lines ~608-626) | Instantiates all tool classes via `ToolRegistry`, assigns names |
| Exposure | `_update_base_tool_set()` (lines ~796-840) | Applies context/environment filters to determine base tool set |
| Activation | `_update_active_tools()` (lines ~904-930) | Applies mode + project filters on top of base set |

These phases touch different parts of the agent's state (`_all_tools`, `_exposed_tools`, `_active_tools`, `_base_toolset`). Understanding how a tool becomes available requires reading across 300+ lines of agent.py. The methods interact implicitly: `_update_active_tools` depends on `_base_toolset` having been computed, which depends on `_update_base_tool_set` having been called, which depends on tool registration in `__init__`.

**Deletion test:** If you delete the tool lifecycle code from agent.py, the complexity doesn't vanish — it reappears wherever anyone needs to know about tool availability. The ordering constraints between registration → exposure → activation are currently implicit.

### Solution

Extract a `ToolManager` class with an explicit 3-phase pipeline:

```python
class ToolManager:
    def register_all(self) -> None:
        """Phase 1: Discover and instantiate all tool classes via ToolRegistry."""
        ...

    def compute_base(self, context: SerenaAgentContext) -> None:
        """Phase 2: Filter tools based on context/environment."""
        ...

    def compute_active(self, mode_manager: ModeManager) -> None:
        """Phase 3: Apply mode + project filters to produce active tool set."""
        ...

    # Read access
    @property
    def all_tools(self) -> dict[type[Tool], Tool]: ...
    @property
    def exposed_tools(self) -> ToolSet: ...
    @property
    def active_tools(self) -> AvailableTools: ...
```

SerenaAgent holds a `ToolManager` instance and delegates. The implicit ordering constraint becomes an explicit pipeline.

### Benefits

- **Locality** — tool lifecycle logic is concentrated in one module, not scattered across agent.py
- **Leverage** — three focused methods replace 100+ lines of inline orchestration in agent.py
- **Testability** — tool activation logic can be tested with a ToolManager + mock ModeManager without a full SerenaAgent
- **Seam** — `compute_base` and `compute_active` become obvious override points for different contexts

---

## Candidate 2 — Extract `ModeManager` from SerenaAgent

**Files:** `agent.py` (ActiveModes nested class at ~lines 217-270, `_update_active_modes` at ~1260-1300)  
**Scope:** Mode management logic embedded inside agent.py

### Problem

Mode management is split across:
- `ActiveModes` — a 53-line class defined *inside* agent.py (not importable)
- `_update_active_modes` method — applies config, project, and override mode defs
- `_session_mode_selection_definition` / `_mode_overrides` — two fields with overlapping purpose
- Implicit cascade: mode changes must trigger tool recomputation via `_update_active_tools()`

The mode resolution pipeline is: config → per-project → session definition → overrides. This is non-trivial logic buried in a private method. The cascade from mode → tool is implicit: every caller of `_update_active_modes` must remember to also call `_update_active_tools`.

### Solution

Extract a `ModeManager` class:

```python
class ModeManager:
    def apply_config(self, config: SerenaConfig) -> None
    def apply_project_config(self, config: ProjectConfig) -> None
    def apply_session_definition(self, definition: ModeSelectionDefinition) -> None
    def apply_overrides(self, overrides: ModeSelectionDefinition) -> None

    @property
    def active_modes(self) -> Sequence[SerenaAgentMode]: ...
    @property
    def tool_inclusion_definitions(self) -> list[...]: ...

    # Explicit signal for the mode→tool cascade
    on_modes_changed: Signal
```

Agent subscribes to `on_modes_changed` to trigger `_update_active_tools` — no implicit coupling.

### Benefits

- **Locality** — mode resolution logic concentrated, not split across __init__, update methods, and nested classes
- **Leverage** — `ModeManager.active_modes` replaces scattered field access
- **Testability** — can test mode composition from config/project/overrides without agent init
- **Seam** — makes it possible to swap mode resolution strategy (e.g., different precedence rules per context)

---

## Candidate 3 — Narrow `Project`: extract `FileSystem` and `MemoryManager`

**Files:** `project.py` (737 lines)  
**Scope:** Project bundles config, file I/O, memories, LS creation

### Problem

`Project` is a shallow bundle — its interface is nearly as complex as its implementation. It does:

- Project configuration (name, root, config load/save)
- File operations (`read_file`, `write_file`, `gather_source_files`, `is_ignored_path`)
- Memory management (`memories_manager`, memory CRUD delegation)
- Language server manager creation (`create_language_server_manager`)
- Ignore pattern gathering (async, from .gitignore + config)
- Source file searching (`search_source_files_for_pattern`)

**Deletion test:** If you delete Project, the complexity doesn't disappear — it scatters across ProjectManager, LanguageServerManager, and all tools. But Project is **shallow**: callers still need to know about file paths, memories, and LS separately. There's no leverage.

### Solution

Extract two adapters from Project:

```python
class Project:
    """Domain entity — identity, config, root path."""
    ...

class FileSystem:
    """File I/O for a project root, respecting ignore patterns."""
    def __init__(self, project_root: str, ignore_patterns: list[str]): ...
    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str) -> None: ...
    def gather_source_files(self) -> list[str]: ...
    def is_ignored_path(self, path: str) -> bool: ...

class ProjectMemoryManager:
    """CRUD for project-scoped memories."""
    def __init__(self, project: Project, ...): ...
    def read(self, name: str) -> str: ...
    def write(self, name: str, content: str) -> None: ...
    # etc.
```

### Benefits

- **Locality** — file system logic and memory logic isolated from each other and from project identity
- **Testability** — `FileSystem` can be tested with temp directories without a Project
- **Seam** — `FileSystem` can have real and in-memory adapters for testing

---

## Candidate 4 — Decouple `_sanitize_for_openai_tools` from `mcp.py`

**Files:** `src/serena/mcp.py` (lines 87-197)  
**Scope:** 110 lines of JSON Schema manipulation in a factory module

### Problem

`_sanitize_for_openai_tools` is 110 lines of deep JSON Schema transformation logic living inside `SerenaMCPFactory` — a module whose job is protocol/factory orchestration. The docstring reads: *"This method was written by GPT-5, I have not reviewed it in detail."*

This is a leaky seam: `SerenaMCPFactory` shouldn't know about OpenAI tool compatibility. The method is only called from one place (`make_mcp_tool`), but it's in the wrong module.

### Solution

Extract into an `OpenAIToolSchemaAdapter`:

```python
class OpenAIToolSchemaAdapter:
    """Transforms MCP tool schemas to be compatible with OpenAI's tool format.
    
    - 'integer' → 'number' (+ multipleOf: 1)
    - Removes 'null' from union types
    - Collapses oneOf/anyOf when they differ only by integer/number
    """
    @staticmethod
    def sanitize(schema: dict) -> dict: ...
```

### Benefits

- **Locality** — schema adaptation logic in its own module, not hiding in a factory
- **Leverage** — `mcp.py` becomes a thinner factory again
- **Testability** — can test schema transformation in isolation

---

## Candidate 5 — Make the mode→tools cascade explicit

**Files:** `agent.py` — `_update_active_modes()` + `_update_active_tools()`  
**Scope:** Implicit dependency between mode changes and tool recomputation

### Problem

The mode→tools cascade is implicit and spread across:
- `_update_active_modes()` — called from `_on_projects_changed`, `_on_project_activated`
- `_update_active_tools()` — must be called separately after every mode change

If someone adds a new code path that changes modes but forgets to call `_update_active_tools`, tools become stale — a runtime bug with no compile-time protection.

### Solution

Merge into a single transaction:

```python
def _refresh_active_state(self) -> None:
    """Atomically recompute modes and tools."""
    self._mode_manager.refresh()
    self._tool_manager.compute_active(self._mode_manager.active_modes)
```

Or use a reactive pattern:

```python
self._mode_manager.on_modes_changed.connect(
    lambda: self._tool_manager.compute_active(self._mode_manager.active_modes)
)
```

### Benefits

- **Locality** — the mode→tool dependency is explicit
- **Leverage** — callers only call `_refresh_active_state()` once
- **Testability** — dependency graph is explicit and mockable
