# Architecture Deepening Opportunities

Analysis date: 2026-05-01  
Context: Post-merge of multi-project branch into main (mode revamp integrated).  
Method: Parallel exploration of agent, tools, LSP, and CLI modules.

---

## ✅ Candidate 1 — Extract `ToolManager` from SerenaAgent (DONE)

**Commit:** `6288f8d1`  
**Created:** `src/serena/tool_manager.py` (ToolManager, ToolSet, AvailableTools)  
**Result:** agent.py -264 lines. Tool lifecycle concentrated in 3-method pipeline.

---

## ✅ Candidate 2 — Extract `ModeManager` from SerenaAgent (DONE)

**Commit:** `5a8e0533`  
**Created:** `src/serena/mode_manager.py` (ModeManager, ActiveModes)  
**Result:** agent.py -70 lines. Mode resolution pipeline (config→projects→session→overrides) concentrated in ModeManager.

---

## ✅ Candidate 3 — Narrow `Project`: extract `ProjectFileSystem` (DONE)

**Commit:** _(pending)_  
**Created:** `src/serena/file_system.py` (ProjectFileSystem)  
**Result:** project.py -140 lines. File operations, ignore patterns, and source file discovery extracted to ProjectFileSystem. Project retains identity/config and LS management, delegates file ops to `project.filesystem`.

---

## Candidate 4

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
