# DAP Multiplexer for Collaborative Debugging

Serena needs a generic (non-JetBrains-specific) debug capability that supports both human-in-the-loop collaborative debugging and autonomous agent triage. We chose a **DAP Multiplexer** — a proxy that sits between the real DAP adapter (debugpy, gdb -i dap, lldb-dap) and multiple DAP clients (the user's IDE plus the agent), rather than building IDE-specific plugins or having the agent work independently with no shared debug state.

The multiplexer enforces a **driver/eavesdropper** model: only one client (the driver) can send mutating commands (step, continue, pause). The human is driver by default; the agent requests control via an HTTP handoff endpoint. The human reclaims control implicitly by sending any step/continue command (last-write-wins). Agent-set breakpoints are cleared on driver reclaim. Pause is always allowed from any client as a safety override.

For autonomous triage, the agent reuses the same multiplexer code path but without an IDE client — it drives the session directly from the start.

## *Why not alternatives*

- **IDE plugin** — ties us to each IDE's extension API, per-IDE maintenance burden. The binary alias approach works across any IDE that supports custom DAP adapter paths.
- **Agent-only (no multiplexer)** — agent and human can't share breakpoints, state, or session. Forces the human to choose between their IDE and the agent.
- **Read-only agent (no driving)** — agent can't step to reach problematic states, severely limiting both collaborative and triage use cases.

## *Consequences*

- The multiplexer is a new component (`serdap/multiplexer.py`) — must be maintained and tested with each DAP adapter.
- Users configure their IDE's debug adapter binary to point at `serdap-mux` — one-time setup per project or globally.
- The driver handoff introduces latency: agent requests control → HTTP endpoint → multiplexer grants → `window/showMessage`. Acceptable for debugging workflows.
- `debugpy` (Python) and `gdb -i dap` / `lldb-dap` (C++) are the initial adapters supported.
