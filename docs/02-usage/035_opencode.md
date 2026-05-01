# Running Serena with OpenCode

This guide walks you through launching the Serena MCP daemon in a way that works seamlessly with OpenCode, performing the session handshake, and monitoring active sessions.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.10+ | Serena is distributed as a Python package. |
| `serena` CLI | Install or upgrade via `pip install --upgrade serena`. |
| OpenCode (2025.12+) | Requires MCP SSE support and tool invocation. |
| Network access | OpenCode must reach the daemon host/port (defaults to `127.0.0.1:8765`). |

## Install or Update Serena

### From PyPI (stable release)

```bash
python -m pip install --upgrade serena
```

### From the vagvaz fork

```bash
python -m pip install --upgrade git+https://github.com/vagvaz/serena.git
```

### From a local clone

```bash
git clone https://github.com/vagvaz/serena
cd serena
uv run serena start-mcp-server --context agent --daemon --daemon-port 8765 --auto-register
```

When running from a local clone, use `uv run serena` instead of `serena` in all subsequent commands, or install the clone in editable mode:

```bash
pip install -e .
```

Optional extras:

- **JetBrains integration**: follow Serena's language-backend docs if you need JetBrains project support.
- **Dashboard**: enabled by default and recommended for tracking sessions.

## Start the Serena MCP Daemon in OpenCode Mode

Launch Serena in daemon mode with automatic project registration:

```bash
serena start-mcp-server \
  --context agent \
  --daemon \
  --daemon-port 8765 \
  --auto-register
```

### Flag overview

- `--daemon`: keeps the MCP server alive and enables SSE transport for multiple clients.
- `--daemon-port`: port used by the SSE endpoint (default `8765`).
- `--auto-register`: allow new filesystem paths provided during session handshake to be registered automatically.
- `--context`: choose the base Serena persona/config; use `agent` unless you have a custom context.

Expected output:

```
Serena daemon started (PID 12345).
  SSE endpoint: http://127.0.0.1:8765/sse
```

The CLI writes its PID to `~/.serena/daemon.pid`. Shut the daemon down with `serena daemon-stop` when finished.

## Connect OpenCode to Serena

### Configure OpenCode

1. Open OpenCode's MCP connection settings.
2. Add a new MCP server entry:
   - **Transport:** SSE
   - **Endpoint:** `http://127.0.0.1:8765/sse`
3. Save and connect.

### Perform the session handshake

OpenCode should invoke the `session_init` tool immediately after connecting. Parameters control per-session behaviour:

| Parameter | Description |
| --- | --- |
| `project` | Absolute project path or registered project name. |
| `context` (optional) | Override the base context (`agent`, `coder`, etc.). |
| `persona` (optional) | Persona name defined in your contexts. |
| `tool_allowlist` (optional) | Restrict this session to specific tools. |
| `backend_hint` (optional) | Hint for non-default language backends (e.g. `jetbrains`). |

Example payload:

```json
{
  "tool": "session_init",
  "arguments": {
    "project": "/path/to/my/repo",
    "context": "agent",
    "persona": "conservative-reviewer",
    "tool_allowlist": ["write_code", "run_tests"],
    "backend_hint": "lsp"
  }
}
```

Behaviour:

1. Serena registers or updates the session, capturing client metadata.
2. When `--auto-register` is set and the path is new, Serena auto-creates the project config.
3. The session binds to the project, persona, and tool allowlist before any further tool executes.

If `--auto-register` is omitted, `session_init` raises an error for unknown paths; register the project manually first.

### Verify the handshake

- The `session_init` tool returns a textual summary confirming bindings.
- Logs contain entries such as `Registered new session …` and `Session … bound to project …`.
- The dashboard (see below) lists the session with its project and heartbeat.

## Operate Serena from OpenCode

- **Tool calls:** read-only tools may run in parallel; write operations are serialized per project.
- **Context/persona overrides:** prompts and tool descriptions adapt according to session configuration.
- **Project resolution:** Serena uses the bound project if OpenCode omits `cwd` in subsequent tool calls.
- **Tool visibility:** when a `tool_allowlist` is supplied, other tools return a not-permitted error.

## Monitor Sessions via the Dashboard

The dashboard starts automatically unless disabled. Default URL: `http://127.0.0.1:8080/dashboard/index.html`.

Key UI elements:

- **Sessions card:** lists active sessions, bound project, client info, and idle time.
- **Projects panel:** shows active projects, attached session counts, and read-only state.
- **Logs tab:** filter by `session_id`, project, and level to isolate activity per OpenCode client.

Refresh the dashboard to confirm that each OpenCode instance has its own session and logs.

## Common Operations

| Task | Command / Action |
| --- | --- |
| Stop the daemon | `serena daemon-stop` |
| Restart dashboard | Use the dashboard restart button or run `serena dashboard-restart`. |
| Manually register a project | `serena project register /path/to/project` then rerun `session_init`. |
| Activate a project manually | Invoke `activate_project_from_path_or_name`. |
| Clear session overrides | Call `session_init` again with empty strings for fields to reset. |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `session_init` reports "Project … is not registered" | Daemon started without `--auto-register`. | Register the project manually or restart with `--auto-register`. |
| Tool calls hit the wrong project | Handshake missing or failed. | Ensure OpenCode calls `session_init` after connecting; inspect logs for errors. |
| Dashboard does not list new session | OpenCode has not invoked any tools yet. | Run `session_init` or another tool, then refresh the dashboard. |
| Logs lack session filter | Stale dashboard assets are cached. | Hard refresh (Ctrl+Shift+R) to load the latest frontend bundle. |
| Auto-registration chose an unexpected project name | Directory lacked `.serena/project.yml`. | Edit the generated config or re-register with the desired name. |

## Experimental Optional LSP Tools

Serena ships additional LSP-based tools that are **disabled by default** and marked as **beta/experimental**.
They provide functionality that not all language servers support (e.g., `textDocument/implementation`).

| Tool | Description |
|------|-------------|
| `find_implementations` | Finds concrete implementations / overrides of a symbol (e.g., subclasses implementing an interface). |
| `find_declaration` | Finds a symbol's declaration by matching a regex with a capture group against the source file (e.g., resolving a call like `obj.method()` to the declared method). |

To enable these, set `included_optional_tools` in your `serena_config.yml` or `project.yml`:

```yaml
included_optional_tools:
  - find_implementations
  - find_declaration
```

You can also enable them per-session by defining a custom [mode or context](../02-usage/050_configuration.md#modes).

## Best Practices

- Use `--auto-register` in shared daemon setups so each OpenCode connection can bring its own project path.
- Always run the handshake before issuing other tools to ensure prompts and tool routing are correct.
- Monitor the dashboard during multi-client sessions to spot stale sessions or misrouted tool calls.
- Secure remote usage with SSH tunnels or reverse proxies; SSE traffic is plain HTTP by default.
- Keep Serena updated alongside OpenCode for compatibility fixes.

With the daemon running in this mode, multiple OpenCode clients can share a single Serena instance while keeping project and persona configuration isolated per session.
