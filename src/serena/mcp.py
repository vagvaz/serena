"""
The Serena Model Context Protocol (MCP) Server
"""

import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import docstring_parser
from mcp.server.fastmcp import server
from mcp.server.fastmcp.server import FastMCP, Settings
from mcp.server.fastmcp.tools.base import Tool as MCPTool
from mcp.types import ToolAnnotations
from pydantic_settings import SettingsConfigDict
import logging

from serena.agent import (
    ProjectNotFoundError,
    SerenaAgent,
    SerenaConfig,
)
from serena.config.context_mode import SerenaAgentContext
from serena.config.serena_config import LanguageBackend, ModeSelectionDefinition
from serena.constants import DEFAULT_CONTEXT, SERENA_LOG_FORMAT
from serena.tool_schema import OpenAIToolSchemaAdapter
from serena.tools import Tool
from serena.util.exception import show_fatal_exception_safe
from serena.util.logging import MemoryLogHandler

log = logging.getLogger(__name__)

# Context variable for passing the cwd from the SSE HTTP connection request
# through to the server lifespan, where it can be used to auto-bind a session
# to a project before any tool call.
_connection_cwd: ContextVar[str | None] = ContextVar("_connection_cwd", default=None)


def configure_logging(*args, **kwargs) -> None:  # type: ignore
    # We only do something here if logging has not yet been configured.
    # Normally, logging is configured in the MCP server startup script.
    # Check if root logger already has handlers rather than using nonexistent logging.is_enabled().
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format=SERENA_LOG_FORMAT)


# patch the logging configuration function in fastmcp, because it's hard-coded and broken
server.configure_logging = configure_logging  # type: ignore


@dataclass
class SerenaMCPRequestContext:
    agent: SerenaAgent


@dataclass
class SerenaConnectionContext:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    client_info: str | None = None


class SerenaMCPFactory:
    """
    Factory for the creation of the Serena MCP server with an associated SerenaAgent.
    """

    def __init__(
        self,
        context: str = DEFAULT_CONTEXT,
        project: str | None = None,
        memory_log_handler: MemoryLogHandler | None = None,
        auto_register_projects: bool = False,
    ):
        """
        :param context: The context name or path to context file
        :param project: Either an absolute path to the project directory or a name of an already registered project.
            If the project passed here hasn't been registered yet, it will be registered automatically and can be activated by its name
            afterward.
        :param memory_log_handler: the in-memory log handler to use for the agent's logging
        :param auto_register_projects: whether to allow on-demand project registration during session handshake
        """
        self.context = SerenaAgentContext.load(context)
        self.project = project
        self.agent: SerenaAgent | None = None
        self.memory_log_handler = memory_log_handler
        self.auto_register_projects = auto_register_projects

    @staticmethod
    def make_mcp_tool(tool: Tool, openai_tool_compatible: bool = True) -> MCPTool:
        """
        Create an MCP tool from a Serena Tool instance.

        :param tool: The Serena Tool instance to convert.
        :param openai_tool_compatible: whether to process the tool schema to be compatible with OpenAI tools
            (doesn't accept integer, needs number instead, etc.). This allows using Serena MCP within codex.
        """
        func_name = tool.get_name()
        func_doc = tool.get_apply_docstring() or ""
        func_arg_metadata = tool.get_apply_fn_metadata()
        is_async = False
        parameters = func_arg_metadata.arg_model.model_json_schema()
        if openai_tool_compatible:
            parameters = OpenAIToolSchemaAdapter.sanitize(parameters)

        docstring = docstring_parser.parse(func_doc)

        # Mount the tool description as a combination of the docstring description and
        # the return value description, if it exists.
        overridden_description = tool.agent.get_context().tool_description_overrides.get(func_name, None)

        if overridden_description is not None:
            func_doc = overridden_description
        elif docstring.description:
            func_doc = docstring.description
        else:
            func_doc = ""
        func_doc = func_doc.strip().strip(".")
        if func_doc:
            func_doc += "."
        if docstring.returns and (docstring_returns_descr := docstring.returns.description):
            # Only add a space before "Returns" if func_doc is not empty
            prefix = " " if func_doc else ""
            func_doc = f"{func_doc}{prefix}Returns {docstring_returns_descr.strip().strip('.')}."

        # Parse the parameter descriptions from the docstring and add pass its description
        # to the parameter schema.
        docstring_params = {param.arg_name: param for param in docstring.params}
        parameters_properties: dict[str, dict[str, Any]] = parameters["properties"]
        for parameter, properties in parameters_properties.items():
            if (param_doc := docstring_params.get(parameter)) and param_doc.description:
                param_desc = f"{param_doc.description.strip().strip('.') + '.'}"
                properties["description"] = param_desc[0].upper() + param_desc[1:]

        # Inject cwd parameter into the tool schema (it lives on apply_ex, not on apply)
        cwd_property = {
            "type": "string",
            "description": "Current working directory for resolving the project context. If provided, the project whose root is a prefix of this path will be used.",
        }
        parameters.setdefault("properties", {})["cwd"] = cwd_property

        def execute_fn(**kwargs) -> str:  # type: ignore
            cwd = kwargs.pop("cwd", None)
            return tool.apply_ex(log_call=True, catch_exceptions=True, cwd=cwd, **kwargs)

        # Generate human-readable title from snake_case tool name
        tool_title = " ".join(word.capitalize() for word in func_name.split("_"))

        # Create annotations with appropriate hints based on tool capabilities
        can_edit = tool.can_edit()
        annotations = ToolAnnotations(
            title=tool_title,
            readOnlyHint=not can_edit,
            destructiveHint=can_edit,
        )

        return MCPTool(
            fn=execute_fn,
            name=func_name,
            description=func_doc,
            parameters=parameters,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
            # keep the value in sync with the kwarg name in Tool.apply_ex. The mcp sdk uses reflection to infer this
            # when the tool is constructed via from_function (which is a bit crazy IMO, but well...)
            context_kwarg="mcp_ctx",
            annotations=annotations,
            title=tool_title,
        )

    class _CwdCaptureMiddleware:
        """
        Raw ASGI middleware that extracts ``cwd`` from the HTTP request
        (query param ``?cwd=`` or header ``X-Cwd`` / ``X-Project``) and
        stores it in ``_connection_cwd`` for the lifespan to consume.

        This runs once per HTTP request to the Starlette app (both SSE GET
        and message POST), but only the SSE lifespan path reads the value.

        Using a plain ASGI middleware (instead of :class:`BaseHTTPMiddleware`)
        avoids implicit ``anyio.to_thread.run_sync`` wrapping and keeps the
        middleware compatible with streaming SSE responses.
        """

        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            if scope["type"] == "http":
                cwd = self._extract_cwd(scope)
                if cwd:
                    _connection_cwd.set(os.path.normpath(cwd))
            await self.app(scope, receive, send)

        @staticmethod
        def _extract_cwd(scope: dict) -> str | None:
            # 1. query string
            qs = scope.get("query_string", b"")
            if qs:
                from urllib.parse import parse_qs

                params = parse_qs(qs.decode("latin-1"))
                cwd = params.get("cwd", [None])[0]
                if cwd:
                    return cwd

            # 2. headers
            for name, value in scope.get("headers", []):
                if name.lower() in (b"x-cwd", b"x-project"):
                    return value.decode("latin-1")
            return None

    def _patch_sse_app(self, mcp: FastMCP) -> None:
        """
        Monkey-patch ``FastMCP.run_sse_async`` on this instance so that the
        Starlette SSE app includes :class:`CwdCaptureMiddleware`, which
        captures the ``cwd`` query parameter or ``X-Cwd`` header from the
        HTTP connection request and stores it in ``_connection_cwd``.

        The lifespan reads ``_connection_cwd`` and auto-binds the session
        to the resolved project before any tool call.
        """
        original_run_sse = mcp.run_sse_async

        async def run_sse_with_cwd(
            self_fastmcp: FastMCP, mount_path: str | None = None
        ) -> None:
            import uvicorn

            starlette_app = self_fastmcp.sse_app(mount_path)

            starlette_app.add_middleware(self._CwdCaptureMiddleware)

            config = uvicorn.Config(
                starlette_app,
                host=self_fastmcp.settings.host,
                port=self_fastmcp.settings.port,
                log_level=self_fastmcp.settings.log_level.lower(),
            )
            server = uvicorn.Server(config)
            await server.serve()

        import functools

        mcp.run_sse_async = functools.partial(run_sse_with_cwd, mcp)

    def _iter_tools(self) -> Iterator[Tool]:
        assert self.agent is not None
        yield from self.agent.get_exposed_tool_instances()

    def _set_mcp_tools(self, mcp: FastMCP, openai_tool_compatible: bool = False) -> None:
        """Update the tools in the MCP server"""
        if mcp is not None:
            # Remove any previously registered tools using the public API
            for tool_name in list(mcp._tool_manager._tools.keys()):
                try:
                    mcp.remove_tool(tool_name)
                except Exception:
                    pass  # ignore if tool was already removed

            # Register Serena tools
            tool_names = []
            for tool in self._iter_tools():
                mcp_tool = self.make_mcp_tool(tool, openai_tool_compatible=openai_tool_compatible)
                mcp._tool_manager._tools[tool.get_name()] = mcp_tool
                tool_names.append(tool.get_name())
            log.info(f"Starting MCP server with {len(tool_names)} tools: {tool_names}")

    def _create_serena_agent(self, serena_config: SerenaConfig, modes: ModeSelectionDefinition | None = None) -> SerenaAgent:
        return SerenaAgent(
            project=self.project,
            serena_config=serena_config,
            context=self.context,
            modes=modes,
            memory_log_handler=self.memory_log_handler,
            auto_register_projects=self.auto_register_projects,
        )

    def _create_default_serena_config(self) -> SerenaConfig:
        return SerenaConfig.from_config_file()

    def create_mcp_server(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        mode_selection_def: ModeSelectionDefinition | None = None,
        language_backend: LanguageBackend | None = None,
        enable_web_dashboard: bool | None = None,
        enable_gui_log_window: bool | None = None,
        open_web_dashboard: bool | None = None,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None,
        trace_lsp_communication: bool | None = None,
        tool_timeout: float | None = None,
    ) -> FastMCP:
        """
        Create an MCP server with process-isolated SerenaAgent to prevent asyncio contamination.

        :param host: The host to bind to
        :param port: The port to bind to
        :param mode_selection_def: the mode selection definition to apply
        :param language_backend: the language backend to use, overriding the configuration setting.
        :param enable_web_dashboard: Whether to enable the web dashboard. If not specified, will take the value from the serena configuration.
        :param enable_gui_log_window: Whether to enable the GUI log window. It currently does not work on macOS, and setting this to True will be ignored then.
            If not specified, will take the value from the serena configuration.
        :param open_web_dashboard: Whether to open the web dashboard on launch.
            If not specified, will take the value from the serena configuration.
        :param log_level: Log level. If not specified, will take the value from the serena configuration.
        :param trace_lsp_communication: Whether to trace the communication between Serena and the language servers.
            This is useful for debugging language server issues.
        :param tool_timeout: Timeout in seconds for tool execution. If not specified, will take the value from the serena configuration.
        """
        try:
            config = self._create_default_serena_config()

            # update configuration with the provided parameters
            if enable_web_dashboard is not None:
                config.web_dashboard = enable_web_dashboard
            if enable_gui_log_window is not None:
                config.gui_log_window = enable_gui_log_window
            if open_web_dashboard is not None:
                config.web_dashboard_open_on_launch = open_web_dashboard
            if log_level is not None:
                log_level = cast(Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], log_level.upper())
                config.log_level = logging.getLevelNamesMapping()[log_level]
            if trace_lsp_communication is not None:
                config.trace_lsp_communication = trace_lsp_communication
            if tool_timeout is not None:
                config.tool_timeout = tool_timeout
            if language_backend is not None:
                config.language_backend = language_backend

            self.agent = self._create_serena_agent(config, mode_selection_def)

        except Exception as e:
            show_fatal_exception_safe(e)
            raise

        # Override model_config to disable the use of `.env` files for reading settings, because user projects are likely to contain
        # `.env` files (e.g. containing LOG_LEVEL) that are not supposed to override the MCP settings;
        # retain only FASTMCP_ prefix for already set environment variables.
        Settings.model_config = SettingsConfigDict(env_prefix="FASTMCP_")
        instructions = self._get_initial_instructions()
        log.info("MCP server initial instructions:\n%s", instructions)
        mcp = FastMCP(
            name="Serena",
            lifespan=self.server_lifespan,
            website_url="https://oraios.github.io/serena",
            host=host,
            port=port,
            instructions=instructions,
        )

        # Patch the SSE transport to inject our cwd-capturing middleware
        self._patch_sse_app(mcp)

        return mcp

    def _auto_init_from_connection_cwd(self, session_id: str) -> str | None:
        """
        Try to auto-initialize the session from ``_connection_cwd`` (set by the
        SSE middleware that captured the ``cwd`` query param or ``X-Cwd`` header).

        :param session_id: the newly-created session ID to bind
        :returns: the resolved project name, or ``None`` if nothing could be resolved
        """
        cwd = _connection_cwd.get()
        if not cwd or not os.path.isdir(cwd):
            return None

        assert self.agent is not None
        serena_config = self.agent.serena_config
        session_manager = self.agent.get_session_manager()
        project_manager = self.agent.get_project_manager()

        # 1. Try to find a registered project matching this path
        registered = serena_config.get_registered_project(cwd)
        if registered is None and self.auto_register_projects:
            # 2. Not registered but auto-register is on — register on the fly
            try:
                serena_config.add_project_from_path(cwd)
                registered = serena_config.get_registered_project(cwd)
            except (FileExistsError, FileNotFoundError) as exc:
                log.info("Could not auto-register project from cwd '%s': %s", cwd, exc)
                return None

        if registered is None:
            log.info("No registered project found for connection cwd '%s' — skipping auto-init", cwd)
            return None

        # 3. Activate the project if not already active
        if not project_manager.is_active(registered.project_name):
            try:
                project = serena_config.get_project(cwd)
                if project is not None:
                    project.set_agent(self.agent)
                    project_manager.add(project)
                    log.info(
                        "Auto-activated project '%s' from connection cwd: %s",
                        registered.project_name, cwd,
                    )
            except Exception as exc:
                log.warning("Failed to activate project '%s': %s", registered.project_name, exc)
                return None

        # 4. Bind the session to this project
        session_manager.set_project(session_id, registered.project_name)
        log.info(
            "Auto-bound session %s to project '%s' from connection cwd: %s",
            session_id, registered.project_name, cwd,
        )
        return registered.project_name

    @asynccontextmanager
    async def server_lifespan(self, mcp_server: FastMCP) -> AsyncIterator[None]:
        """Manage server startup and shutdown lifecycle.

        In SSE/daemon mode, the lifespan is entered per-connection. The agent
        must persist across connections, so we only set up tools here and
        defer shutdown to the daemon process signal handler.

        Session tracking: on entry, we register the session with the SessionManager
        so that subsequent tool calls can resolve the correct project per-client.

        IMPORTANT: We yield immediately so the SSE endpoint event is sent to the client.
        Tool setup happens after the connection is established (tools are registered
        on the server at creation time, not per-connection).
        """
        assert self.agent is not None
        session_manager = self.agent.get_session_manager()

        # Extract session ID and client info from the MCP connection
        connection_ctx = SerenaConnectionContext()

        # Try to auto-initialize from SSE-level cwd (set by middleware)
        self._auto_init_from_connection_cwd(connection_ctx.session_id)

        openai_tool_compatible = self.context.name in ["chatgpt", "codex", "oaicompat-agent"]
        self._set_mcp_tools(mcp_server, openai_tool_compatible=openai_tool_compatible)
        log.info("MCP server lifetime setup complete")
        try:
            yield connection_ctx
        finally:
            # Unregister session on disconnect
            if connection_ctx.session_id:
                session_manager.unregister_session(connection_ctx.session_id)
            log.info("MCP server connection closed (agent persists in daemon mode)")
            # NOTE: Do NOT call self.agent.on_shutdown() here.
            # In SSE/daemon mode, lifespan is entered per-connection and the agent
            # must persist. Shutdown is handled by the daemon's SIGTERM/SIGINT handlers.
            # In stdio mode, the process exits naturally after the single connection.

    def _get_initial_instructions(self) -> str:
        assert self.agent is not None
        return self.agent.create_connection_prompt()
