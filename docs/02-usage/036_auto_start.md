# Auto-Starting the Serena Daemon

When using Serena in daemon mode with OpenCode or other MCP clients, you may want the daemon to start automatically rather than manually launching it each time. Here are three approaches:

## Option 1: Wrapper Script

Create a script that starts the daemon if it isn't already running:

```bash
#!/bin/bash
# ~/bin/serena-ensure-running.sh
PID_FILE=~/.serena/daemon.pid
if [ ! -f "$PID_FILE" ] || ! kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    serena start-mcp-server --context agent --daemon --daemon-port 8765 --auto-register &
    sleep 2  # wait for SSE endpoint to be ready
fi
```

Make it executable:
```bash
chmod +x ~/bin/serena-ensure-running.sh
```

Then run it before starting OpenCode, or add it to your shell profile.

## Option 2: systemd Service (Linux, Recommended)

Create `~/.config/systemd/user/serena-daemon.service`:

```ini
[Unit]
Description=Serena MCP Daemon
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/serena start-mcp-server --context agent --daemon --daemon-port 8765 --auto-register
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Enable and start:
```bash
systemctl --user daemon-reload
systemctl --user enable --now serena-daemon
```

**Benefits:**
- Auto-starts on user login
- Automatically restarts on crash
- No shell startup delay
- Managed via standard systemd commands (`systemctl --user status serena-daemon`)

## Option 3: Shell Profile Hook

Add to `~/.zshrc` or `~/.bashrc`:

```bash
# Auto-start Serena daemon if not running
if [ ! -f ~/.serena/daemon.pid ] || ! kill -0 $(cat ~/.serena/daemon.pid) 2>/dev/null; then
    serena start-mcp-server --context agent --daemon --daemon-port 8765 --auto-register &>/dev/null &
fi
```

**Drawback:** Adds a small delay to every shell session startup.

## Verifying the Daemon

Check if the daemon is running:
```bash
serena daemon-status
```

Stop it manually:
```bash
serena daemon-stop
```

Restart the dashboard:
```bash
serena restart-dashboard
```
