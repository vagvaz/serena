import json
import logging

from serena.tools import Tool, ToolMarkerBeta, ToolMarkerOptional
from serdap.adapter_config import AdapterConfig, DebugAdapterLanguage, get_adapter_config
from serdap.dap_client import DapClient
from serdap.debug_adapter import DebugAdapterProcess
from serdap.multiplexer import Multiplexer
from serdap.session_manager import DebugSessionManager

log = logging.getLogger(__name__)

_global_multiplexer: Multiplexer | None = None
_global_dap_client: DapClient | None = None


def _get_or_create_session(project, language: str = "python") -> tuple[Multiplexer, DapClient] | None:
    global _global_multiplexer, _global_dap_client
    if _global_multiplexer is not None and _global_dap_client is not None:
        return _global_multiplexer, _global_dap_client

    project_name = project.project_name if project else "default"
    manager = DebugSessionManager.get_instance()

    existing = manager.get_session(project_name)
    if existing is not None and existing.dap_client is not None:
        _global_multiplexer = existing.multiplexer
        _global_dap_client = existing.dap_client
        return existing.multiplexer, existing.dap_client

    try:
        lang = DebugAdapterLanguage(language)
    except ValueError:
        lang = DebugAdapterLanguage.PYTHON

    adapter_config = get_adapter_config(lang)
    mux = Multiplexer(
        adapter_config=adapter_config,
        language=lang,
        session_manager=manager,
        project_name=project_name,
    )
    mux.start()

    client = DapClient(port=mux.tcp_port)
    client.connect()

    manager.create_session(project_name, mux, client)
    _global_multiplexer = mux
    _global_dap_client = client
    return mux, client


class DebugStartTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Start a debug session for the current project."""

    def apply(
        self,
        target: str = "",
        cwd: str | None = None,
        lang: str = "python",
    ) -> str:
        """
        Start a debug session. Spawns the DAP adapter, starts the multiplexer
        TCP server, and opens an agent DAP client connection. Performs the
        DAP initialization handshake (initialize, launch, configurationDone).

        The IDE can connect to the multiplexer's TCP port to share the session.
        The agent connects as a real DAP client and is visible to the multiplexer
        alongside the IDE.

        :param target: the target program to debug (path to script or executable)
        :param cwd: optional working directory for the debug session
        :param lang: the language of the debug target ('python' or 'cpp')
        :return: JSON with session info and adapter capabilities
        """
        try:
            check_lang = DebugAdapterLanguage(lang)
        except ValueError:
            check_lang = DebugAdapterLanguage.PYTHON
        cfg = get_adapter_config(check_lang)
        error = DebugAdapterProcess.verify(cfg)
        if error:
            return json.dumps({"status": "error", "message": error})

        pair = _get_or_create_session(self.project, lang)
        if pair is None:
            return json.dumps({"status": "error", "message": "Failed to create debug session"})
        mux, client = pair

        mux.start_adapter()

        init_resp = client.send_initialize(adapter_id=lang)
        if not init_resp.get("success", False):
            return json.dumps({
                "status": "error",
                "message": f"Initialize failed: {init_resp.get('message', 'unknown error')}",
                "raw": init_resp,
            })

        launch_args: dict = {}
        if target:
            launch_args["program"] = target
        if cwd:
            launch_args["cwd"] = cwd

        launch_resp = client.send_request("launch", launch_args)
        config_resp = client.send_request("configurationDone")

        client.discarding_events()

        body = init_resp.get("body", {}) or {}
        return json.dumps({
            "status": "ok",
            "tcp_port": mux.tcp_port,
            "handoff_port": mux.get_handoff_port(),
            "adapter_capabilities": body,
            "launch_success": launch_resp.get("success", False),
            "configuration_done": config_resp.get("success", False),
            "message": f"Debug session started. IDE can connect to tcp://127.0.0.1:{mux.tcp_port}. "
                       f"Handoff at http://127.0.0.1:{mux.get_handoff_port()}/handoff?to=agent",
        })


class DebugStopTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Stop the current debug session."""

    def apply(self) -> str:
        """
        Stop the current debug session, disconnect the adapter, and clean up resources.

        :return: status message
        """
        project_name = self.project.project_name if self.project else "default"
        manager = DebugSessionManager.get_instance()
        session = manager.get_session(project_name)
        if session is None:
            return json.dumps({"status": "error", "message": "No active debug session"})

        client = session.dap_client
        try:
            if client is not None:
                resp = client.send_request("disconnect", {"terminateDebuggee": True}, timeout=5.0)
            else:
                resp = {"success": False, "message": "No DAP client"}
        except Exception:
            resp = {"success": False, "message": "disconnect failed (adapter may have already exited)"}

        session.close()
        manager.close_session(project_name)
        global _global_multiplexer, _global_dap_client
        _global_multiplexer = None
        _global_dap_client = None

        return json.dumps({
            "status": "ok",
            "disconnect_success": resp.get("success", False),
            "message": "Debug session stopped",
        })


class DebugSetBreakpointTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Set a breakpoint in the debug session."""

    def apply(
        self,
        file: str,
        line: int,
        condition: str | None = None,
    ) -> str:
        """
        Set a breakpoint at the specified file and line. Returns the breakpoint
        verification status (whether it was actually set by the debugger).

        :param file: the source file path
        :param line: the line number
        :param condition: optional condition expression
        :return: JSON with breakpoint result
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair

        bp = {"line": line}
        if condition:
            bp["condition"] = condition

        resp = client.send_request("setBreakpoints", {
            "source": {"path": file},
            "breakpoints": [bp],
        })

        body = resp.get("body") or {}
        bps_set = body.get("breakpoints", [])
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "breakpoints": bps_set,
            "message": f"Breakpoint at {file}:{line}"
                       + ("" if not bps_set else " (verified)" if bps_set[0].get("verified") else " (not verified)"),
        })


class DebugClearAllBreakpointsTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Clear all breakpoints in the debug session."""

    def apply(self) -> str:
        """
        Clear all breakpoints currently set in the debug session.

        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair

        resp = client.send_request("setBreakpoints", {
            "source": {"path": ""},
            "breakpoints": [],
        })

        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "message": "All breakpoints cleared",
        })


class DebugStackTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Get the current call stack."""

    def apply(
        self,
        thread_id: int | None = None,
    ) -> str:
        """
        Get the current call stack. If no thread_id is given, fetches the list
        of threads first and returns stack for the first suspended thread.

        :param thread_id: optional thread ID
        :return: JSON with stack frames
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair

        if thread_id is None:
            threads_resp = client.send_request("threads")
            body = threads_resp.get("body") or {}
            threads = body.get("threads", [])
            if not threads:
                return json.dumps({
                    "status": "ok",
                    "threads": [],
                    "message": "No active threads",
                })
            thread_id = threads[0]["id"]

        resp = client.send_request("stackTrace", {"threadId": thread_id})
        body = resp.get("body") or {}
        frames = body.get("stackFrames", [])
        total_frames = body.get("totalFrames", len(frames))

        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "thread_id": thread_id,
            "total_frames": total_frames,
            "stack_frames": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "source": (f.get("source") or {}).get("path", "unknown"),
                    "line": f["line"],
                    "column": f.get("column", 0),
                }
                for f in frames
            ],
        })


class DebugVariablesTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Get variables for a stack frame."""

    def apply(
        self,
        frame_id: int,
    ) -> str:
        """
        Get the variables for the specified stack frame. First fetches the
        scopes for the frame, then retrieves variables for each scope.

        :param frame_id: the stack frame ID
        :return: JSON with scopes and variables
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair

        scopes_resp = client.send_request("scopes", {"frameId": frame_id})
        scopes_body = scopes_resp.get("body") or {}
        scopes = scopes_body.get("scopes", [])

        result_scopes = []
        for scope in scopes:
            scope_info = {
                "name": scope.get("name"),
                "variablesReference": scope.get("variablesReference", 0),
                "expensive": scope.get("expensive", False),
            }
            if scope.get("variablesReference", 0) > 0:
                vars_resp = client.send_request("variables", {
                    "variablesReference": scope["variablesReference"],
                })
                vars_body = vars_resp.get("body") or {}
                raw_vars = vars_body.get("variables", [])
                scope_info["variables"] = [
                    {
                        "name": v.get("name"),
                        "value": v.get("value"),
                        "type": v.get("type"),
                        "variablesReference": v.get("variablesReference", 0),
                    }
                    for v in raw_vars
                ]
            result_scopes.append(scope_info)

        return json.dumps({
            "status": "ok" if scopes_resp.get("success") else "error",
            "frame_id": frame_id,
            "scopes": result_scopes,
        })


class DebugEvaluateTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Evaluate an expression in the debug session."""

    def apply(
        self,
        expression: str,
        frame_id: int | None = None,
    ) -> str:
        """
        Evaluate an expression in the current debug context.

        :param expression: the expression to evaluate
        :param frame_id: optional frame ID for context
        :return: JSON with evaluation result
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair

        args: dict = {"expression": expression}
        if frame_id is not None:
            args["frameId"] = frame_id

        resp = client.send_request("evaluate", args)
        body = resp.get("body") or {}

        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "result": body.get("result"),
            "type": body.get("type"),
            "variablesReference": body.get("variablesReference", 0),
            "message": resp.get("message", ""),
        })


class DebugNextTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Step over (next line). Requires driver."""

    def apply(
        self,
        thread_id: int | None = None,
    ) -> str:
        """
        Step over to the next line. Requires driver control.

        :param thread_id: optional thread ID
        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        mux, client = pair

        if not mux.is_driver_agent:
            return json.dumps({"status": "error", "message": "Agent does not have driver control. Use debug_take_control first."})

        args: dict = {}
        if thread_id is not None:
            args["threadId"] = thread_id
        else:
            threads_resp = client.send_request("threads")
            body = threads_resp.get("body") or {}
            threads = body.get("threads", [])
            if threads:
                args["threadId"] = threads[0]["id"]

        resp = client.send_request("next", args)
        stopped = client.wait_for_stopped()
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "message": "Step over" if resp.get("success") else f"Step over failed: {resp.get('message', '')}",
            "stopped": stopped,
        })


class DebugStepInTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Step into a function call. Requires driver."""

    def apply(
        self,
        thread_id: int | None = None,
    ) -> str:
        """
        Step into a function. Requires driver control.

        :param thread_id: optional thread ID
        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        mux, client = pair

        if not mux.is_driver_agent:
            return json.dumps({"status": "error", "message": "Agent does not have driver control. Use debug_take_control first."})

        args: dict = {}
        if thread_id is not None:
            args["threadId"] = thread_id
        else:
            threads_resp = client.send_request("threads")
            body = threads_resp.get("body") or {}
            threads = body.get("threads", [])
            if threads:
                args["threadId"] = threads[0]["id"]

        resp = client.send_request("stepIn", args)
        stopped = client.wait_for_stopped()
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "message": "Step in" if resp.get("success") else f"Step in failed: {resp.get('message', '')}",
            "stopped": stopped,
        })


class DebugStepOutTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Step out of the current function. Requires driver."""

    def apply(
        self,
        thread_id: int | None = None,
    ) -> str:
        """
        Step out of the current function. Requires driver control.

        :param thread_id: optional thread ID
        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        mux, client = pair

        if not mux.is_driver_agent:
            return json.dumps({"status": "error", "message": "Agent does not have driver control. Use debug_take_control first."})

        args: dict = {}
        if thread_id is not None:
            args["threadId"] = thread_id
        else:
            threads_resp = client.send_request("threads")
            body = threads_resp.get("body") or {}
            threads = body.get("threads", [])
            if threads:
                args["threadId"] = threads[0]["id"]

        resp = client.send_request("stepOut", args)
        stopped = client.wait_for_stopped()
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "message": "Step out" if resp.get("success") else f"Step out failed: {resp.get('message', '')}",
            "stopped": stopped,
        })


class DebugContinueTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Continue execution. Requires driver."""

    def apply(
        self,
        thread_id: int | None = None,
    ) -> str:
        """
        Continue execution. Requires driver control.

        :param thread_id: optional thread ID
        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        mux, client = pair

        if not mux.is_driver_agent:
            return json.dumps({"status": "error", "message": "Agent does not have driver control. Use debug_take_control first."})

        args: dict = {}
        if thread_id is not None:
            args["threadId"] = thread_id
        else:
            threads_resp = client.send_request("threads")
            body = threads_resp.get("body") or {}
            threads = body.get("threads", [])
            if threads:
                args["threadId"] = threads[0]["id"]

        resp = client.send_request("continue", args)
        stopped = client.wait_for_stopped()
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "message": "Continue" if resp.get("success") else f"Continue failed: {resp.get('message', '')}",
            "stopped": stopped,
        })


class DebugAwaitStopTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Wait for execution to stop (breakpoint hit, step complete, pause)."""

    def apply(
        self,
        timeout: float = 30.0,
    ) -> str:
        """
        Block until the debugee stops (breakpoint, step, pause, exception).
        Use this after ``debug_continue`` to wait for a breakpoint to be hit,
        or after ``debug_next``/``debug_step_in``/``debug_step_out`` to ensure
        the step completed before inspecting state.

        Events other than ``stopped`` (e.g. ``output``, ``continued``) are
        silently discarded.

        :param timeout: maximum seconds to wait (default 30.0)
        :return: JSON with stop reason, threadId, and description
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair
        body = client.await_stop(timeout=timeout)
        if body is None:
            return json.dumps({"status": "timeout", "message": "No stopped event received within timeout"})
        return json.dumps({
            "status": "ok",
            "reason": body.get("reason"),
            "thread_id": body.get("threadId"),
            "description": body.get("description", ""),
            "text": body.get("text", ""),
        })


class DebugSetExceptionBreakpointsTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Control which exceptions pause execution."""

    def apply(
        self,
        filters: list[str] | None = None,
    ) -> str:
        """
        Set exception breakpoint filters. Common filter values:

        - ``["all"]`` — pause on all exceptions
        - ``["uncaught"]`` — pause on uncaught exceptions only
        - ``[]`` — don't pause on any exceptions
        - ``["raised", "uncaught"]`` — pause on both raised and uncaught

        The exact set of supported filters depends on the debug adapter.
        For CPython/debugpy: ``"raised"`` and ``"uncaught"``.

        :param filters: list of exception filter IDs. Default ``["uncaught"]``.
        :return: JSON with result status
        """
        if filters is None:
            filters = ["uncaught"]
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair
        resp = client.send_request("setExceptionBreakpoints", {"filters": filters})
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "filters": filters,
            "message": f"Exception breakpoints set to {filters}"
                       if resp.get("success") else f"Failed: {resp.get('message', '')}",
        })


class DebugTakeControlTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Request driver control of the debug session."""

    def apply(self) -> str:
        """
        Request driver control of the debug session from the human.
        The multiplexer will grant driver to the agent and notify the IDE.

        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        mux, _client = pair
        result = mux.handoff_to_agent()
        return json.dumps({"status": "ok", "message": result})


class DebugPauseTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Pause execution. Always allowed (safety override)."""

    def apply(
        self,
        thread_id: int | None = None,
    ) -> str:
        """
        Pause execution. Unlike step/continue, pause is always allowed regardless
        of driver status (safety override).

        :param thread_id: optional thread ID
        :return: status message
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        _mux, client = pair

        args: dict = {}
        if thread_id is not None:
            args["threadId"] = thread_id

        resp = client.send_request("pause", args)
        return json.dumps({
            "status": "ok" if resp.get("success") else "error",
            "message": "Pause requested" if resp.get("success") else f"Pause failed: {resp.get('message', '')}",
        })


class DebugStatusTool(Tool, ToolMarkerOptional, ToolMarkerBeta):
    """Get the current debug session status."""

    def apply(self) -> str:
        """
        Get the current status of the debug session including driver info,
        connected clients, breakpoints, etc.

        :return: JSON with session status
        """
        pair = _get_or_create_session(self.project)
        if pair is None:
            return json.dumps({"status": "error", "message": "No debug session"})
        mux, _client = pair
        return json.dumps({
            "status": "ok",
            "tcp_port": mux.tcp_port,
            "handoff_port": mux.get_handoff_port(),
            "is_driver_agent": mux.is_driver_agent,
            "client_breakpoints": mux.get_all_client_breakpoints(),
        })
