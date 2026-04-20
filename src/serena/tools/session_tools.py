from __future__ import annotations

from collections.abc import Sequence

from serena.tools import Tool, ToolMarkerDoesNotRequireActiveProject
from serena.tools.tools_base import get_current_session_id


class SessionInitTool(Tool, ToolMarkerDoesNotRequireActiveProject):
    """Initialize per-session configuration for daemon clients."""

    def apply(
        self,
        project: str | None = None,
        context: str | None = None,
        persona: str | None = None,
        tool_allowlist: Sequence[str] | None = None,
        backend_hint: str | None = None,
    ) -> str:
        """
        Initialize per-session configuration for daemon clients.

        Call this tool after connecting to set up project, context, persona,
        and tool visibility for your session.
        """
        session_id = get_current_session_id()
        if session_id is None:
            return "Error: Session initialization requires an MCP connection context."

        try:
            state = self.agent.initialize_session(
                session_id,
                project=project,
                context=context,
                persona=persona,
                tool_allowlist=list(tool_allowlist) if tool_allowlist is not None else None,
                backend_hint=backend_hint,
            )
        except ValueError as exc:
            return f"Error: {exc}"

        messages: list[str] = [f"Session '{session_id}' registered."]
        if state.project_name:
            messages.append(f"Bound to project '{state.project_name}'.")
        elif project:
            messages.append("Project activation requested but no project is active. Verify the path/name and try again.")
        if state.context_name:
            messages.append(f"Context override set to '{state.context_name}'.")
        if state.persona_name:
            messages.append(f"Persona override set to '{state.persona_name}'.")
        if state.tool_allowlist:
            allowlist_str = ", ".join(sorted(state.tool_allowlist))
            messages.append(f"Tool allowlist applied: {allowlist_str}.")
        if state.backend_hint:
            messages.append(f"Preferred backend hint: {state.backend_hint}.")

        return "\n".join(messages)
