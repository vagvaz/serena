# Bug: daemon-status shows wrong endpoint path

## Description

`serena daemon-status` reports the MCP endpoint as `http://127.0.0.1:8765/mcp`, but the actual SSE endpoint is `/sse` (FastMCP default). Attempting to connect to `/mcp` returns HTTP 404.

## Location

`serena/cli.py` line 481:

```python
click.echo("  Endpoint: http://127.0.0.1:8765/mcp")
```

## Root cause

The path `/mcp` is hardcoded. Serena uses `FastMCP` from the `mcp` Python SDK, which defaults to serving SSE at `/sse` (configurable via `sse_path`) and messages at `/messages/` (configurable via `message_path`). Neither the CLI nor config expose these FastMCP path settings.

## Fix options

1. Read the actual `sse_path` from the FastMCP settings and use it in `daemon-status`
2. Or simply change the hardcoded path to `/sse`

## Impact

OpenCode (and other MCP clients) connecting to the serena daemon get a 404 if they use the path reported by `daemon-status`.
