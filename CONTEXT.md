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

### 3. Server Layer (items 12, 13)

Standalone, no ordering dependencies:
- **#12 (MCP shim)** — confirm no external callers of `_sanitize_for_openai_tools`, redirect lone internal caller to `OpenAIToolSchemaAdapter`, delete shim.
- **#13 (MCP endpoint)** — replace 3 hardcoded `/mcp` paths in `cli.py` with the path derived from the selected transport (FastMCP uses `/sse`).
