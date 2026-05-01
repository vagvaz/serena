# `SolidLanguageServer` — Improvement Roadmap

## Overview

`SolidLanguageServer` (`src/solidlsp/ls.py`, 2732 lines) is the core LSP framework class that has grown into a god-class. The issues below range from critical correctness bugs to moderate maintainability concerns. This document tracks them and proposes remedy directions.

---

## Critical

### 1. God-class: `SolidLanguageServer` (2732 lines)

The class mixes ~19 LSP request methods, two-tier caching (raw + processed symbols), file buffer management, symbol tree construction, workspace edit application, ignore-path matching, body creation, and cache persistence. The caching pattern is substantially duplicated across the raw and high-level code paths.

**Suggested fix:** Extract into separate classes:

| Concern | Suggested class | Lines |
|---------|----------------|-------|
| Raw document symbol caching | `RawSymbolCache` | ~1314–1363, ~2420–2470 |
| High-level (processed) symbol caching | `HighLevelSymbolCache` | ~1406–1529, ~2500–2570 |
| File buffer open/close/dirty tracking | `FileBufferManager` | ~170–230, ~1160–1210 |
| Ignore spec / path matching | Already partially in `PathSpec` | ~600–620 |
| WorkspaceEdit application | Keep or extract | ~2677–2694 |

### 2. "HORRIBLE HACK" symbol heuristics (line 1889)

The method for finding the containing symbol of a variable reference parses source text by splitting on `.` to guess variable names. This is explicitly self-documented as a "horrible hack" and produces wrong results for any language that doesn't use Python-style dot notation.

**Suggested fix:** Replace with a dedicated LSP `textDocument/documentSymbol` request scoped to the reference line, then walk the resulting symbol tree to find the innermost containing symbol. This is more expensive but correct.

---

## High

### 3. No unit tests for `SolidLanguageServer`

All ~742 tests in `test/solidlsp/` are integration tests that require real language server binaries (pyright, gopls, rust-analyzer, etc.) to be installed and running. The core class has zero isolated unit tests for:
- Caching logic (monolithic + per-file)
- Symbol conversion (raw → processed)
- Ignore-path / filename matching

**Suggested fix:** Add a test suite using mocked `LanguageServerProcess` and fixture symbol data. The `serena_bug.md` test protocol handler at `test/solidlsp/csharp/test_csharp_basic.py:48ff` is a pattern — expand it.

### 4. 7+ LS-specific startup race conditions

Multiple language server implementations acknowledge that the server signals readiness before it can actually serve requests. Fixes are papered over with `time.sleep()` or polling loops:

| File | Line(s) | Issue |
|------|---------|-------|
| `clangd_language_server.py` | 365, 415 | "Should we wait for…" / "defeats the purpose of the event" |
| `rust_analyzer.py` | 697 | Same pattern |
| `intelephense.py` | 192, 197, 207 | "Probably incorrect" init wait + explicit sleep |
| `omnisharp.py` | 255 | Same pattern |

**Suggested fix:** Standardize on a `threading.Event`-based readiness protocol in the base class. Subclasses signal when the server is truly ready for requests; the base class waits with timeout + health check.

### 5. Overgrown `Tool.apply_ex` (tools_base.py:426–572, 146 lines)

The hottest code path in the system handles: session ID extraction, project resolution, argument-based project inference, tool allowlist enforcement, active-tool check, LS failure retry, cache saving, and timeout wrapping. Too many concerns are intermixed.

**Suggested fix:** Delegate into pipeline stages:
- `SessionResolver` — session / project binding
- `ToolVisibilityEnforcer` — allowlist + active check
- `ExecutionGuard` — retry + circuit breaker + timeout

---

## Medium

### 6. No unit tests concurrency / race scenarios

The `ReadWriteLock` in `task_executor.py` and `apply_ex` retry logic have no tests exercising concurrent tool calls, project activation races, or LS restart races.

**Suggested fix:** Add tests with `threading.Barrier` to force interleaving at known points.

### 7. No structured error taxonomy

Tools return free-form string errors starting with `"Error:"` in inconsistent formats. Clients parsing tool output programmatically have no structured error envelope to rely on.

**Suggested fix:** Introduce an `ErrorCode` enum and return structured error dicts with `"error_code"` and `"message"` keys alongside (or instead of) plain strings. Start with the most common failure modes: `PROJECT_NOT_FOUND`, `LS_NOT_READY`, `TOOL_NOT_ALLOWED`, `TIMEOUT`.

### 8. No circuit breaker for repeated LS failures

`apply_ex` retries exactly once when the LS crashes (tools_base.py:514–527). If the restart succeeds but crashes again on the next call, this loops with no backoff, no circuit breaker, and no user-visible warning.

**Suggested fix:** Add a per-LS `CircuitBreaker` that trips after N rapid failures, holds open for a backoff window, and surfaces a clear error to the caller. Reuse the existing `threading.Event` pattern.

### 9. `SolidLanguageServer` dual initialization path (DEPRECATED path)

The `process_launch_info` parameter is marked DEPRECATED (ls.py:490) but the constructor still branches on it. All subclasses pass `None` and use `_create_dependency_provider()` instead.

**Suggested fix:** Remove the deprecated path and simplify the constructor.

### 10. Cache versioning is fragile

Subclass authors must manually increment `cache_version_raw_document_symbols` and override `_document_symbols_cache_fingerprint` when they change symbol processing. There's no compile-time or runtime enforcement — it's easy to forget.

**Suggested fix:** Add an assertion or health check during startup that logs a warning if the LS subclass cache version hasn't been bumped since the file's modification time.

---

## Low

### 11. `request_completions` retry loop (ls.py:1231)

The completion request polls up to 30 times when the server returns `isIncomplete=True`. This has no backoff and no limit on total wall-clock time.

**Suggested fix:** Add a total timeout (e.g., 5 s) in addition to the iteration cap.

### 12. Dead backward-compat shim in mcp.py (line 92–100)

`_sanitize_for_openai_tools` now delegates entirely to `OpenAIToolSchemaAdapter` but is kept "for backward compatibility during the refactoring transition."

**Suggested fix:** Remove if no callers remain.

### 13. Hardcoded MCP endpoint path in CLI (cli.py:481)

`daemon-status` reports the endpoint as `/mcp` but FastMCP serves at `/sse`. Clients connecting to the reported endpoint get HTTP 404.

**Suggested fix:** Derive the path from the selected transport rather than hardcoding.
