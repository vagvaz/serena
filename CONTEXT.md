# Serena — Context

## Architectural Roadmaps

The `ls_improvements.md` document has been split into three independent roadmaps.

### 1. `solidlsp/ls.py` Roadmap

Execution order — **dependency-ordered, highest-risk last:**

1. **Unit tests** for `SolidLanguageServer` — mock at LSP protocol level (override `server.send.document_symbol`), no real LS binaries needed. Provides safety net for subsequent changes.
2. **Horrible hack fix** (ls.py:1889) — replace Python-specific string-split heuristic with a `textDocument/documentSymbol` request scoped to the reference line. Cache per file to avoid N round-trips.
3. **Startup race conditions** (clangd, rust-analyzer, intelephense, omnisharp) — standardize on `threading.Event`-based readiness protocol in base class. Test with fake LS process + smoke tests.
4. **God-class refactor** — extract `RawSymbolCache`, `HighLevelSymbolCache`, `FileBufferManager` from the 2732-line `SolidLanguageServer`. This fold in:
   - **Item 9** — Remove deprecated `process_launch_info` constructor branch (all subclasses use `_create_dependency_provider()` now).
   - **Item 10** — Cache versioning becomes an internal detail of extracted classes (auto-managed instead of manual bumping).
5. **Dropped:** Item 11 (completions retry loop) — never observed as a problem in practice.

### 2. Tool Execution Pipeline (items 5, 6, 7, 8)

Execution order:

1. **Error taxonomy** (#7) — standalone, unlocks the rest.
2. **Circuit breaker** (#8) — depends on #7 for structured error reporting.
3. **apply_ex refactor** (#5) — last, after interfaces settle.
4. **Concurrency tests** (#6) — parallel to all of the above.

## Language: Debug

**DAP Multiplexer**:
A proxy that sits between the real debug adapter (debugpy, gdb -i dap) and multiple DAP clients, enabling a shared debug session.
_Avoid_: Debug proxy, debug bridge

**Driver**:
The DAP client currently allowed to send mutating commands (step, continue, pause).
_Avoid_: Controller, primary client

**Eavesdropper**:
A DAP client connected to the multiplexer that can read state (stack, variables, evaluate) but cannot send mutating commands.

**Handoff**:
Transfer of the driver role from one DAP client to another. The agent requests handoff via an HTTP endpoint; the human reclaims implicitly by sending any step/continue command.
_Avoid_: Takeover, switch

**Agent Breakpoints**:
Breakpoints set by the agent in a collaborative session, automatically cleared when the human reclaims the driver role.

## Relationships

- The **Multiplexer** manages one **Driver** and zero or more **Eavesdroppers** per session
- An **Agent Breakpoint** is only meaningful in a collaborative session; in autonomous triage, all breakpoints are "agent breakpoints" but none are auto-cleared
- A **Handoff** changes which client is **Driver**; the previous Driver becomes an **Eavesdropper**

## Flagged ambiguities

- "debug session" was used to mean both "a DAP adapter running a process" and "the human working in their IDE" — resolved: these are two clients of the same **Multiplexer** session.

### 3. Server Layer (items 12, 13)

Standalone, no ordering dependencies:
- **#12 (MCP shim)** — confirm no external callers of `_sanitize_for_openai_tools`, redirect lone internal caller to `OpenAIToolSchemaAdapter`, delete shim.
- **#13 (MCP endpoint)** — replace 3 hardcoded `/mcp` paths in `cli.py` with the path derived from the selected transport (FastMCP uses `/sse`).
