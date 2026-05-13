"""
The Serena Model Context Protocol (MCP) Server
"""

import json
import multiprocessing
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from logging import Logger
from typing import TYPE_CHECKING, Optional, TypeVar

import requests
import webview
import logging
from serena.util.misc import mark_used
from serena.util.logging import LogTime
from serena.util.string_utils import dict_string

from interprompt.jinja_template import JinjaTemplate
from serena import serena_version
from serena.analytics import RegisteredTokenCountEstimator, ToolUsageStats
from serena.config.context_mode import SerenaAgentContext, SerenaAgentMode
from serena.config.serena_config import (
    LanguageBackend,
    ModeSelectionDefinition,
    RegisteredProject,
    SerenaConfig,
    SerenaPaths,
)
from serena.dashboard import DashboardPortFile, SerenaDashboardAPI, SerenaDashboardTrayManager, SerenaDashboardViewer, open_url_in_browser
from serena.ls_manager import LanguageServerManager
from serena.project import MemoriesManager, Project
from serena.project_manager import ProjectManager
from serena.prompt_factory import SerenaPromptFactory
from serena.task_executor import TaskExecutor
from serena.session_manager import SessionManager, SessionState
from serena.mode_manager import ActiveModes, ModeManager
from serena.tool_manager import ToolManager
from serena.tools import (
    ReadMemoryTool,
    Tool,
)
from serena.util.gui import system_has_usable_display
from serena.util.logging import MemoryLogHandler
from solidlsp.ls_config import Language

if TYPE_CHECKING:
    from serena.gui_log_viewer import GuiLogViewer

log = logging.getLogger(__name__)
TTool = TypeVar("TTool", bound="Tool")
T = TypeVar("T")
SUCCESS_RESULT = "OK"

class ProjectNotFoundError(Exception):
    pass






class ProjectPromptProvisionStatus:
    """
    Manages the status of the provision of project-specific prompts
    """

    @dataclass
    class SessionStatus:
        mode_prompts_provided: bool = False
        project_activation_message_provided: bool = False

    def __init__(self, newly_activated_mode_names: set[str] | None = None):
        """
        :param newly_activated_mode_names: list of mode names that have been newly activated (by dynamic project activation)
            and for which prompts must still be provided (either in the system prompt or via the activation message)
        """
        if newly_activated_mode_names is None:
            newly_activated_mode_names = set()
        self._newly_activated_mode_names: set[str] = newly_activated_mode_names
        self._session_status_dict: dict[str, ProjectPromptProvisionStatus.SessionStatus] = defaultdict(lambda: self.SessionStatus())

    def _get_session_status(self, session_id: str) -> SessionStatus:
        return self._session_status_dict[session_id]

    def is_mode_prompt_already_provided(self, mode_name: str, session_id: str) -> bool:
        """
        :param mode_name: the mode name
        :param session_id: the client session ID
        :return: whether the mode name was already provided (in a project-specific activation message) and therefore
            should not be included again (in the Serena instructions manual)
        """
        if not self._get_session_status(session_id).mode_prompts_provided:
            return False
        return mode_name in self._newly_activated_mode_names

    def get_modes_with_prompts_to_be_provided_for_project_activation(self, session_id: str) -> list[SerenaAgentMode]:
        """
        Gets the modes that have been newly activated and for which prompts still need to be provided
        (in dynamic project activation message).

        :param: session_id: the client session ID
        :return: the modes
        """
        result = []

        # Note: We always want to provide the prompts of newly activated modes in the activation message
        #   because some clients (e.g. Claude Desktop) use a single session for all chats.
        #   Therefore, we view project activation as an "entry action", which must always provide
        #   all the information that is relevant to the project
        # Because of this, we cannot use a condition like this:
        #   new_mode_prompts_must_be_provided_for_activation = not self._get_session_status(session_id).mode_prompts_provided
        new_mode_prompts_must_be_provided_for_activation = True
        mark_used(session_id)

        if new_mode_prompts_must_be_provided_for_activation:
            for mode_name in self._newly_activated_mode_names:
                mode = ActiveModes.get_mode_instance(mode_name)
                if mode.has_prompt():
                    result.append(mode)
        return result

    def mark_mode_prompts_as_provided(self, session_id: str) -> None:
        """
        Marks the prompts for all newly activated modes as provided, so that they will not be included in the project activation message.

        :param session_id: the client session ID
        """
        self._get_session_status(session_id).mode_prompts_provided = True

    def mark_project_activation_message_as_provided(self, session_id: str) -> None:
        """
        Marks the project activation message as provided, so that it will not be included again in case of multiple activations of the same project.

        :param session_id: the client session ID
        """
        self._get_session_status(session_id).project_activation_message_provided = True

    def is_project_activation_message_already_provided(self, session_id: str) -> bool:
        """
        :param session_id: the client session ID
        :return: whether the project activation message was already provided and therefore should not be included again
        """
        return self._get_session_status(session_id).project_activation_message_provided


class DashboardManager:
    class Mode(Enum):
        BROWSER = "browser"
        """
        Open the dashboard in the default browser; supported on all platforms.
        """
        WEBVIEW = "app"
        """
        Open the dashboard via a native window (using pywebview) which minimises to the tray;
        supported on Windows and macOS (but on macOS, tray apps for multiple instances accumulate 
        in the top bar, which users may not want)
        """
        TRAY_MANAGER = "tray_manager"
        """
        Register dashboard instance with a central manager tray app (single tray icon for all instances), 
        spawning the tray manager if not already running; supported on macOS and Windows.
        """

        @classmethod
        def from_platform(cls) -> "DashboardManager.Mode":
            match platform.system():
                case "Windows":
                    return cls.WEBVIEW
                case "Darwin":
                    # TODO: Switch to TRAY_MANAGER once support is tested
                    return cls.BROWSER
                case _:
                    return cls.BROWSER

        def is_supported(self) -> bool:
            """
            :return: whether the mode is supported on the current platform
            """
            if self == DashboardManager.Mode.WEBVIEW:
                return SerenaDashboardViewer.is_current_platform_supported()
            elif self == DashboardManager.Mode.TRAY_MANAGER:
                return SerenaDashboardTrayManager.is_current_platform_supported()
            else:
                return True

    def __init__(
        self,
        port: int,
        host_listen_address: str,
        open_dashboard_on_launch: bool,
        active_project: Project | None = None,
        mode_str: str | None = None,
    ):
        # determine requested mode
        if mode_str is not None:
            try:
                mode = self.Mode(mode_str)
            except ValueError:
                mode = self.Mode.from_platform()
                log.warning(f"Invalid dashboard interface mode '{mode_str}' specified; falling back to platform default '{mode.value}'.")
        else:
            mode = self.Mode.from_platform()

        # check for mode compatibility
        if not mode.is_supported():
            fallback_mode = self.Mode.from_platform()
            log.warning(
                f"Dashboard interface mode '{mode.value}' is not supported on the current platform; "
                "falling back to '{fallback_mode.value}'."
            )
            mode = fallback_mode

        self._port = port
        self._mode = mode
        self._dashboard_viewer_process: multiprocessing.Process | None = None
        self._tray_manager_lock = threading.Lock()

        dashboard_host = host_listen_address
        if dashboard_host == "0.0.0.0":
            dashboard_host = "localhost"
        self.url = f"http://{dashboard_host}:{port}/dashboard/index.html"

        # handle startup
        match self._mode:
            case self.Mode.WEBVIEW:
                self._start_dashboard_viewer(minimized=not open_dashboard_on_launch)
            case self.Mode.TRAY_MANAGER:
                init_fn = lambda: self._tray_manager_register(open_on_launch=open_dashboard_on_launch, active_project=active_project)
                threading.Thread(target=init_fn, name="init-DashboardTrayManager", daemon=True).start()
            case self.Mode.BROWSER:
                if open_dashboard_on_launch:
                    if not system_has_usable_display():
                        log.info("Not opening the Serena dashboard because no usable display was detected.")
                    else:
                        self.open_dashboard_in_browser()

    def open_dashboard_in_browser(self) -> None:
        open_url_in_browser(self.url, use_subprocess=True)

    @staticmethod
    def _start_dashboard_viewer_process_function(url: str, minimized: bool, parent_process_id: int) -> None:
        """
        Main function of the subprocess for starting the dashboard viewer
        """
        try:
            SerenaDashboardViewer(url, start_minimized=minimized, parent_process_id=parent_process_id).run()
        except webview.errors.WebViewException as e:
            log.warning(f"Could not open Serena Dashboard viewer. Cause:\n{e}")
            # Fall back to opening the browser window if the window was supposed to be shown directly
            if not minimized:
                open_url_in_browser(url, use_subprocess=True)

    def _start_dashboard_viewer(self, minimized: bool) -> None:
        """
        Starts the dashboard viewer (in a separate process) or, if the current platform does not support it,
        opens the dashboard in the default web browser.

        :param minimized: whether the dashboard viewer should be started minimized (if supported on the current platform).
            If the viewer is not supported on the current platform, then this controls whether to open the browser window.
        """
        self._dashboard_viewer_process = multiprocessing.Process(
            target=self._start_dashboard_viewer_process_function, args=(self.url, minimized, os.getpid()), daemon=True
        )
        self._dashboard_viewer_process.start()

    def _tray_manager_register(self, open_on_launch: bool, active_project: Project | None) -> None:
        """
        Ensure the tray manager is running and register this dashboard instance with it.

        If the current platform supports the native tray manager, this method starts
        the manager (if not already running) and registers the instance. Otherwise,
        it falls back to opening the dashboard in the default web browser.

        :param open_on_launch: whether the dashboard should be opened immediately
        """
        with LogTime("Dashboard tray manager initialisation"):
            with self._tray_manager_lock:
                # ensure the singleton tray manager process is running
                SerenaDashboardTrayManager.ensure_running()

                # determine the current project name (if any)
                project_name = active_project.project_name if active_project is not None else None

                # register this instance with the tray manager
                SerenaDashboardTrayManager.register_instance(
                    port=self._port,
                    dashboard_url=self.url,
                    project=project_name,
                    started_at=datetime.now().isoformat(timespec="seconds"),
                    open_viewer=open_on_launch,
                )

    def shutdown(self) -> None:
        """
        Frees resources, terminating the dashboard viewer process (if any) and unregistering from the tray manager (if applicable).
        """
        if self._dashboard_viewer_process is not None:
            log.info("Stopping the dashboard viewer process ...")
            self._dashboard_viewer_process.terminate()
            self._dashboard_viewer_process = None

        if self._mode == self.Mode.TRAY_MANAGER:
            with self._tray_manager_lock:
                SerenaDashboardTrayManager.unregister_instance(port=self._port)

    def update_active_project(self, active_project: Project | None) -> None:
        """
        Updates the active project (where applicable).

        :param active_project: the currently active project or None if no project is active
        """
        if self._mode == self.Mode.TRAY_MANAGER:
            with self._tray_manager_lock:
                project_name = active_project.project_name if active_project is not None else None
                SerenaDashboardTrayManager.update_project(port=self._port, project=project_name)


class SerenaAgent:
    def __init__(
        self,
        project: str | None = None,
        project_activation_callback: Callable[[], None] | None = None,
        serena_config: SerenaConfig | None = None,
        context: SerenaAgentContext | None = None,
        modes: ModeSelectionDefinition | None = None,
        memory_log_handler: MemoryLogHandler | None = None,
        auto_register_projects: bool = False,
    ):
        """
        :param project: the project to load immediately or None to not load any project; may be a path to the project or a name of
            an already registered project;
        :param project_activation_callback: a callback function to be called when a project is activated.
        :param serena_config: the Serena configuration or None to read the configuration from the default location.
        :param context: the context in which the agent is operating, None for default context.
            The context may adjust prompts, tool availability, and tool descriptions.
        :param modes: mode selection definition to apply for this session
        :param memory_log_handler: a MemoryLogHandler instance from which to read log messages; if None, a new one will be created
            if necessary.
        :param auto_register_projects: whether the agent may automatically register previously unseen projects when given a
            filesystem path (e.g. via session handshake). Defaults to False for safety.
        """
        self._session_manager = SessionManager()
        self._session_context_overrides: dict[str, SerenaAgentContext] = {}
        self._gui_log_viewer: Optional["GuiLogViewer"] = None
        self._dashboard_viewer_process: multiprocessing.Process | None = None
        self._dashboard_manager: DashboardManager | None = None
        self._auto_register_projects = auto_register_projects
        self._memory_log_handler: MemoryLogHandler | None = None
        self._project_prompt_status = ProjectPromptProvisionStatus()
        self._session_mode_selection_definition = modes
        self._mode_manager = ModeManager()
        if self._session_mode_selection_definition is not None:
            self._mode_manager.apply_session_definition(self._session_mode_selection_definition)
        self.version = serena_version()

        # obtain serena configuration using the decoupled factory function
        self.serena_config = serena_config or SerenaConfig.from_config_file()

        # propagate configuration to other components
        self.serena_config.propagate_settings()

        # determine registered project to be activated (if any)
        registered_project_to_activate: RegisteredProject | None = (
            self.serena_config.get_registered_project(project, autoregister=True) if project is not None else None
        )

        # adjust log level
        serena_log_level = self.serena_config.log_level
        if Logger.root.level != serena_log_level:
            log.info(f"Changing the root logger level to {serena_log_level}")
            Logger.root.setLevel(serena_log_level)

        # open GUI log window if enabled
        if self.serena_config.gui_log_window:
            log.info("Opening GUI window")
            if platform.system() == "Darwin":
                log.warning("GUI log window is not supported on macOS")
            else:
                # even importing on macOS may fail if tkinter dependencies are unavailable (depends on Python interpreter installation
                # which uv used as a base, unfortunately)
                from serena.gui_log_viewer import GuiLogViewer

                self._gui_log_viewer = GuiLogViewer(
                    "dashboard",
                    title="Serena Logs",
                    memory_log_handler=self._get_memory_log_handler(),
                    shutdown_handler=lambda: self.shutdown(),
                )
                self._gui_log_viewer.start()
        else:
            log.debug("GUI window is disabled")

        # set the agent context
        if context is None:
            context = SerenaAgentContext.load_default()
        self._context = context

        # instantiate all tool classes via ToolManager
        self._tool_manager = ToolManager()
        tool_names = self._tool_manager.register_all(self)

        # If GUI log window is enabled, set the tool names for highlighting
        if self._gui_log_viewer is not None:
            self._gui_log_viewer.set_tool_names(tool_names)

        token_count_estimator = RegisteredTokenCountEstimator[self.serena_config.token_count_estimator]
        log.info(f"Will record tool usage statistics with token count estimator: {token_count_estimator.name}.")
        self._tool_usage_stats = ToolUsageStats(token_count_estimator)

        # log fundamental information
        log.info(
            f"Starting Serena server (version={self.version}, process id={os.getpid()}, parent process id={os.getppid()}; "
            f"language backend={self.serena_config.language_backend.name}); Python version={platform.python_version()}, platform={platform.platform()}"
        )
        log.info("Configuration file: %s", self.serena_config.config_file_path)
        log.info("Available projects: {}".format(", ".join(self.serena_config.project_names)))
        log.info(f"Loaded tools ({len(self._tool_manager.all_tools)}): {', '.join([tool.get_name_from_cls() for tool in self._tool_manager.all_tools.values()])}")

        self._check_shell_settings()

        # determine the effective language backend for this session.
        # If a startup project is provided and has a per-project override, use it; otherwise use the global config.
        # Since we don't want to change the toolset after startup, the language backend cannot be changed within a running Serena session
        self._language_backend = self.serena_config.language_backend
        if registered_project_to_activate is not None and registered_project_to_activate.project_config.language_backend is not None:
            self._language_backend = registered_project_to_activate.project_config.language_backend
            log.info(f"Using language backend as configured in project.yml: {self._language_backend.name}")
        else:
            log.info(f"Using language backend from global configuration: {self._language_backend.name}")

        # create executor for starting the language server and running tools in another thread
        # This executor is used to achieve linear task execution
        self._task_executor = TaskExecutor("SerenaAgentTaskExecutor")

        # create the ProjectManager — owns the lifecycle of N active projects
        self._project_manager = ProjectManager(
            serena_config=self.serena_config,
            session_manager=self._session_manager,
            task_executor=self._task_executor,
            language_backend=self._language_backend,
            on_projects_changed=self._on_projects_changed,
        )

        # Initialize the prompt factory
        self.prompt_factory = SerenaPromptFactory()

        # activate the startup project (if any) using ProjectManager
        # Note: We cannot update the active tools yet, because the base toolset has not been computed yet
        #       (and its computation depends on the active project)
        startup_project_instance: Project | None = None
        self._mode_manager.apply_config(self.serena_config)
        self._mode_manager.apply_session_definition(self._session_mode_selection_definition)
        self._project_activation_callback = project_activation_callback
        self._project_prompt_status = ProjectPromptProvisionStatus()
        if project is not None:
            try:
                _proj = self._project_manager.resolve_project(project, self.serena_config)
                if _proj is not None:
                    _proj.set_agent(self)
                    self._project_manager.add(_proj, notify=False)
                    startup_project_instance = _proj
            except Exception as e:
                log.error(f"Error activating project '{project}' at startup: {e}", exc_info=e)
        self._update_active_modes()

        # determine the base toolset defining the set of exposed tools (which e.g. the MCP shall see),
        self._tool_manager.compute_base(
            self.serena_config, self._language_backend, self._context, self._mode_manager.active_modes, startup_project_instance
        )

        # update the active tools (considering the active project, if any)
        self._tool_manager.compute_active(self._mode_manager.active_modes, self._project_manager)

        # Restore previously active projects from disk state
        # (set_agent is called inside the restore loop below)
        for registered in self.serena_config.projects:
            try:
                state_file = os.path.join(registered.project_root, ".serena", "active_state.json")
                if not os.path.exists(state_file):
                    continue
                with open(state_file) as f:
                    json.load(f)  # validate but don't use values
                project_instance = registered.get_project_instance(self.serena_config)
                if project_instance:
                    project_instance.set_agent(self)
                    self._project_manager.add(project_instance, notify=False)
                    log.info("Restored project '%s' from disk state", project_instance.project_name)
            except Exception as e:
                log.warning("Failed to restore project '%s' from disk: %s", registered.project_name, e)

        # Ensure restored projects influence initial state
        self._refresh_active_state()

        # Start the idle project checker
        self._project_manager.start_idle_checker()

        # start the dashboard (web frontend), registering its log handler
        # should be the last thing to happen in the initialization since the dashboard
        # may access various parts of the agent
        if self.serena_config.web_dashboard:
            self._dashboard_thread, port = SerenaDashboardAPI(
                self._get_memory_log_handler(), tool_names, agent=self, tool_usage_stats=self._tool_usage_stats
            ).run_in_thread(host=self.serena_config.web_dashboard_listen_address)
            self._dashboard_manager = DashboardManager(
                port,
                self.serena_config.web_dashboard_listen_address,
                self.serena_config.web_dashboard_open_on_launch,
                next(iter(self._project_manager.get_all().values()), None),
                mode_str=self.serena_config.web_dashboard_interface,
            )
            log.info("Serena web dashboard started at %s", self._dashboard_manager.url)
            # Persist dashboard port so the CLI restart-dashboard command can find it
            DashboardPortFile.default().write(port)
            # inform the GUI window (if any)
            if self._gui_log_viewer is not None:
                self._gui_log_viewer.set_dashboard_url(self._dashboard_manager.url)

        self._send_usage_info()

    def _get_memory_log_handler(self) -> MemoryLogHandler:
        """Return the memory log handler, creating one if necessary."""
        if self._memory_log_handler is None:
            self._memory_log_handler = MemoryLogHandler(level=self.serena_config.log_level)
            Logger.root.addHandler(self._memory_log_handler)
        return self._memory_log_handler

    def restart_dashboard(self) -> str:
        """Restart the dashboard web server without affecting LSP processes or tool execution.

        The dashboard is stateless (reads live from the agent), so restarting it is safe.
        The old daemon thread will die when the Flask server socket closes.
        """
        if not self.serena_config.web_dashboard:
            return "Dashboard is not enabled in configuration"

        # Store old port to try reusing it
        old_url = self._dashboard_url
        host = self.serena_config.web_dashboard_listen_address

        # The old thread is a daemon, so it will die when the Flask server stops.
        # We can't gracefully stop Flask, but since it's a daemon thread on a bound port,
        # we just start a new one. The old server will fail to bind if the port is still
        # in use, so we let run_in_thread find the next free port.
        log.info("Restarting dashboard...")
        tool_names = [tool.get_name() for tool in self.get_exposed_tool_instances()]
        self._dashboard_thread, port = SerenaDashboardAPI(
            self._get_memory_log_handler(), tool_names, agent=self, tool_usage_stats=self._tool_usage_stats
        ).run_in_thread(host=host)

        dashboard_host = host if host != "0.0.0.0" else "localhost"
        self._dashboard_url = f"http://{dashboard_host}:{port}/dashboard/index.html"
        DashboardPortFile.default().write(port)
        log.info("Serena web dashboard restarted at %s", self._dashboard_url)

        # Update GUI window if present
        if self._gui_log_viewer is not None:
            self._gui_log_viewer.set_dashboard_url(self._dashboard_url)

        return f"Dashboard restarted at {self._dashboard_url}"

    def _send_usage_info(self) -> None:
        if os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("SERENA_USAGE_REPORTING") == "false":
            return
        params: dict[str, str | int] = {
            "os": platform.system(),
            "dashboard": int(self.serena_config.web_dashboard),
            "version": self.version,
            "backend": self._language_backend.value,
            "context": self._context.name,
        }
        try:
            requests.get("https://oraios-software.de/serena_usage.php", params=params, timeout=1)
        except Exception as e:
            log.debug(f"Failed to send usage info: {e}")

    def _create_base_toolset(
        self,
        serena_config: SerenaConfig,
        language_backend: LanguageBackend,
        context: SerenaAgentContext,
        modes: ActiveModes,
        project: Project | None,
    ) -> None:
        """
        Delegates to ToolManager.compute_base() to determine the exposed tool set.

        Kept as an instance method for backward compatibility during the refactoring
        transition; callers should use self._tool_manager.compute_base() directly.
        """
        self._tool_manager.compute_base(serena_config, language_backend, context, modes, project)

    def get_language_backend(self) -> LanguageBackend:
        return self._language_backend

    def get_current_tasks(self) -> list[TaskExecutor.TaskInfo]:
        """
        Gets metadata for tasks currently running or waiting to acquire execution slots.
        The returned TaskInfo objects are thread-safe snapshots that can be inspected outside
        of the agent lock.

        :return: the list of tasks known to the executor at call time
        """
        return self._task_executor.get_current_tasks()

    def get_last_executed_task(self) -> TaskExecutor.TaskInfo | None:
        """
        Gets the last executed task.

        :return: the last executed task info or None if no task has been executed yet
        """
        return self._task_executor.get_last_executed_task()

    def get_language_server_manager(self) -> LanguageServerManager | None:
        # Return the LS manager from the first active project, or None
        for project in self._project_manager.get_all().values():
            return project.language_server_manager
        return None

    def get_language_server_manager_or_raise(self) -> LanguageServerManager:
        # Use the project context from tool execution (set by apply_ex)
        from serena.tools.tools_base import _current_project

        project = _current_project.get()
        if project is None:
            # If no context is set, try the first active project (defensive fallback)
            first = next(iter(self._project_manager.get_all().values()), None)
            if first is None:
                raise ValueError("No active project.")
            project = first
        return project.get_language_server_manager_or_raise()

    def get_log_inspection_instructions(self) -> str:
        if self.serena_config.web_dashboard:
            return f"Live logs can be inspected via the dashboard at {self.get_dashboard_url()}"
        else:
            log_path = SerenaPaths().last_returned_log_file_path
            if log_path is not None:
                return f"Find the current log file here: {log_path}"
            else:
                return "Unfortunately, logs are not available. We recommend enabling the web dashboard/logging in general."

    def get_context(self) -> SerenaAgentContext:
        return self._context

    def get_tool_description_override(self, tool_name: str) -> str | None:
        return self._context.tool_description_overrides.get(tool_name, None)

    def _check_shell_settings(self) -> None:
        # On Windows, Claude Code sets COMSPEC to Git-Bash (often even with a path containing spaces),
        # which causes all sorts of trouble, preventing language servers from being launched correctly.
        # So we make sure that COMSPEC is unset if it has been set to bash specifically.
        if platform.system() == "Windows":
            comspec = os.environ.get("COMSPEC", "")
            if "bash" in comspec:
                os.environ["COMSPEC"] = ""  # force use of default shell
                log.info("Adjusting COMSPEC environment variable to use the default shell instead of '%s'", comspec)

    def record_tool_usage(self, input_kwargs: dict, tool_result: str | dict, tool: Tool) -> None:
        """
        Record the usage of a tool with the given input and output strings if tool usage statistics recording is enabled.
        """
        tool_name = tool.get_name()
        input_str = str(input_kwargs)
        output_str = str(tool_result)
        log.debug(f"Recording tool usage for tool '{tool_name}'")
        self._tool_usage_stats.record_tool_usage(tool_name, input_str, output_str)

    def get_dashboard_url(self) -> str | None:
        """
        :return: the URL of the web dashboard, or None if the dashboard is not running
        """
        dm = getattr(self, '_dashboard_manager', None)
        if dm is None:
            return None
        return dm.url

    def open_dashboard(self) -> bool:
        """
        Opens the Serena dashboard (for on-demand usage as triggered by the user, e.g. via a tool)

        :return: True if the dashboard was opened, False if it could not be opened
        """
        dm = getattr(self, '_dashboard_manager', None)
        if dm is None:
            raise Exception("Dashboard is not running.")

        if not system_has_usable_display():
            log.warning("Not opening the Serena web dashboard because no usable display was detected.")
            return False

        self._dashboard_manager.open_dashboard_in_browser()
        return True

    def get_exposed_tool_instances(self) -> list["Tool"]:
        """
        :return: the tool instances which are exposed (e.g. to the MCP client).
            Note that the set of exposed tools is fixed for the session, as
            clients don't react to changes in the set of tools, so this is the superset
            of tools that can be offered during the session.
            If a client should attempt to use a tool that is dynamically disabled
            (e.g. because a project is activated that disables it), it will receive an error.
        """
        return list(self._tool_manager.exposed_tools.tools)

    # ── Project query methods (delegate to ProjectManager) ─────────────────

    def get_active_project_by_name(self, name: str) -> Project | None:
        """
        Look up an active project by its canonical name.

        :param name: the project name
        :returns: the Project, or ``None`` if not active
        """
        return self._project_manager.get_by_name(name)

    def get_all_active_projects(self) -> dict[str, Project]:
        """
        Return a snapshot of all active projects.

        :returns: ``{project_name: Project}``
        """
        return self._project_manager.get_all()

    def resolve_project_for_path(self, cwd: str) -> Project | None:
        """
        Find the active project whose root is a prefix of the given path.
        Uses longest-prefix matching to handle nested projects correctly.

        :param cwd: an absolute path (e.g. current working directory)
        :return: the matching Project, or None if no active project matches
        """
        return self._project_manager.resolve_for_path(cwd)

    def resolve_session_project(self, session_id: str | None, cwd: str | None) -> Project | None:
        """
        Resolve the project for a tool call based on session and working directory.

        Resolution order (via :class:`ProjectManager`):
        1. Resolve from *cwd* using longest-prefix matching; cache in session manager.
        2. Fall back to session manager's existing project binding.
        3. Return ``None`` — the caller must error, not guess.

        :param session_id: the MCP session/client identifier
        :param cwd: the current working directory of the tool call
        :return: the resolved Project, or None if no project can be determined
        """
        return self._project_manager.resolve_for_session(session_id, cwd)

    def get_session_project(self, session_id: str) -> Project | None:
        """
        Get the project bound to a session without resolving from cwd.

        :param session_id: the MCP session/client identifier
        :return: the cached Project, or None
        """
        return self._project_manager.get_session_project(session_id)

    def get_session_manager(self) -> SessionManager:
        """Return the session manager for multi-client daemon support."""
        return self._session_manager

    def get_project_manager(self) -> ProjectManager:
        """Return the project manager for active project lifecycle."""
        return self._project_manager

    def get_session_state(self, session_id: str) -> SessionState | None:
        """Return the SessionState for the given session ID, if known."""
        return self._session_manager.get_session(session_id)

    def ensure_session_registered(self, session_id: str, *, client_info: str | None = None) -> SessionState:
        """Ensure the session is registered and marked active."""
        return self._session_manager.register_session(session_id, client_info=client_info)

    def initialize_session(
        self,
        session_id: str,
        *,
        project: str | None = None,
        context: str | None = None,
        persona: str | None = None,
        tool_allowlist: Sequence[str] | None = None,
        backend_hint: str | None = None,
        client_info: str | None = None,
    ) -> SessionState:
        """Apply handshake metadata to a session and optionally activate/bind a project."""

        log.debug(
            "Initializing session %s (project=%s, context=%s, persona=%s, backend_hint=%s)",
            session_id,
            project,
            context,
            persona,
            backend_hint,
        )

        # Apply context override if provided
        if context:
            try:
                context_obj = SerenaAgentContext.load(context)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(f"Failed to load context '{context}': {exc}") from exc
            self._session_context_overrides[session_id] = context_obj
        elif context == "":
            # explicit request to clear context override
            self._session_context_overrides.pop(session_id, None)

        # Register/update the session with provided metadata
        state = self._session_manager.register_session(
            session_id,
            client_info=client_info,
            project_name=None,
            context_name=context or None,
            persona_name=persona,
            tool_allowlist=tool_allowlist,
            backend_hint=backend_hint,
        )

        # Handle project activation/binding after registration
        if project:
            activation_target = project
            registered_project = self.serena_config.get_project(activation_target)
            if registered_project is None and os.path.isdir(activation_target) and not self._auto_register_projects:
                raise ValueError(
                    f"Project '{activation_target}' is not registered. Launch Serena with --auto-register to allow on-demand "
                    "registration, or register the project manually before connecting."
                )
            try:
                was_new_activation = self.activate_project_from_path_or_name(activation_target)
                log.debug(
                    "Session %s activated project via handshake (target=%s, new_activation=%s)",
                    session_id,
                    activation_target,
                    was_new_activation,
                )
            except ProjectNotFoundError as exc:
                raise ValueError(f"Failed to activate project '{activation_target}': {exc}") from exc
            except Exception as exc:
                raise ValueError(f"Failed to activate project '{activation_target}': {exc}") from exc

            # Determine the canonical project name after activation
            activated_project = self.serena_config.get_project(activation_target)
            if activated_project is None and os.path.isdir(activation_target):
                activated_project = self._project_manager.resolve_for_path(os.path.abspath(activation_target))
            if activated_project is not None:
                canonical_name = activated_project.project_name
                state = self._session_manager.update_session(
                    session_id,
                    project_name=canonical_name,
                    client_info=client_info,
                )
            else:
                log.warning(
                    "Handshake activated project '%s' but could not resolve canonical name; session %s remains unbound",
                    activation_target,
                    session_id,
                )

        return state

    # ── Idle timeout tracking ──────────────────────────────────────────────

    def _touch_project(self, project: Project) -> None:
        """Update the last-active timestamp for a project (delegates to ProjectManager)."""
        self._project_manager.touch(project)

    def _persist_all_projects(self) -> None:
        """Save state for all active projects (delegates to ProjectManager)."""
        self._project_manager.persist_all()

    def get_active_modes(self) -> list[SerenaAgentMode]:
        """
        :return: the list of active modes
        """
        return list(self._mode_manager.active_modes.get_modes())

    def _format_prompt(self, prompt_template: str) -> str:
        template = JinjaTemplate(prompt_template)
        return template.render(available_tools=self._tool_manager.exposed_tools.tool_names, available_markers=self._tool_manager.exposed_tools.tool_marker_names)

    def create_connection_prompt(self) -> str:
        """Return the initial instructions prompt shown when an MCP client connects."""
        return self.prompt_factory.create_connection_prompt()

    def create_system_prompt(self, session_id: str | None = None) -> str:
        if session_id is None:
            try:
                from serena.tools.tools_base import get_current_session_id

                session_id = get_current_session_id()
            except Exception:  # pragma: no cover - defensive fallback
                session_id = None

        session_state = self.get_session_state(session_id) if session_id else None
        context_override = self._session_context_overrides.get(session_id) if session_id else None
        effective_context = context_override or self._context

        available_tools = self._tool_manager.active_tools
        available_markers = available_tools.tool_marker_names
        tool_names = available_tools.tool_names
        if session_state and session_state.tool_allowlist:
            allowlist = set(session_state.tool_allowlist)
            tool_names = [name for name in tool_names if name in allowlist]

        global_memories = MemoriesManager(
            serena_data_folder=None, read_only_memory_patterns=self.serena_config.read_only_memory_patterns
        ).list_global_memories()
        global_memories_str = dict_string(global_memories.to_dict()) if len(global_memories) > 0 else ""
        log.info(
            "Generating system prompt with available_tools=(see active tools), available_markers=%s, session_id=%s",
            available_markers,
            session_id,
        )
        system_prompt = self.prompt_factory.create_system_prompt(
            context_system_prompt=self._format_prompt(effective_context.prompt),
            mode_system_prompts=[self._format_prompt(mode.prompt) for mode in self.get_active_modes()],
            available_tools=tool_names,
            available_markers=available_markers,
            global_memories_list=global_memories_str,
        )

        # If a session has a project bound, append its activation message
        if session_state and session_state.project_name:
            project = self._project_manager.get_by_name(session_state.project_name)
            if project is not None and not self._project_prompt_status.is_project_activation_message_already_provided(session_id):
                system_prompt += "\n\n" + self._get_project_activation_message(project, session_id=session_id)

        if session_state and session_state.persona_name:
            system_prompt += f"\nPersona: {session_state.persona_name}"

        log.info("System prompt:\n%s", system_prompt)
        return system_prompt

    def _get_project_activation_message(self, project: Project, session_id: str | None = None) -> str:
        """
        :param project: the project that was activated
        :param session_id: optional session ID for tracking prompt provision status
        :return: a message providing information about the given project upon activation.
        """
        proj = project
        assert proj is not None, "A project must be active before calling this."

        # Note: The activation message is always returned in full, even if it was already provided in the current session,
        #   because some clients (e.g. Claude Desktop) will use the same session across multiple chats.
        #   So while we don't want the activation message to be additionally included in the system prompt
        #   (initial_instructions), an explicit project activation should always return it.
        # (The check below deliberately left in place for documentation purposes, preventing a regression)
        if self._project_prompt_status.is_project_activation_message_already_provided(session_id):
            pass  # no special handling

        # provide basic project information (name, location, languages, encoding)
        if proj.is_newly_created:
            msg = f"Created and activated a new project with name '{proj.project_name}' at {proj.project_root}. "
        else:
            msg = f"The project with name '{proj.project_name}' at {proj.project_root} is activated."
        if self._language_backend == LanguageBackend.LSP:
            languages_str = ", ".join([lang.value for lang in proj.project_config.languages])
            msg += f"\nProgramming languages: {languages_str}."
        msg += f"File encoding: {proj.project_config.encoding}."

        # add list of memories (if memories are enabled)
        include_memories = self._tool_manager.active_tools.contains_tool_class(ReadMemoryTool)
        if include_memories:
            project_memories = proj.memories_manager.list_project_memories()
            if project_memories:
                msg += (
                    f"\n{json.dumps(project_memories.to_dict())}\n"
                    + "Use the `read_memory` tool to read these memories later if they are relevant to the task."
                )

        # add prompts for modes that were dynamically activated by the project
        modes_with_prompts = self._project_prompt_status.get_modes_with_prompts_to_be_provided_for_project_activation(session_id)
        if modes_with_prompts:
            msg += "\nNewly applicable mode instructions:"
            for mode in modes_with_prompts:
                msg += f"\n{mode.prompt}"
        self._project_prompt_status.mark_mode_prompts_as_provided(session_id)

        # add project-specific prompt
        if proj.project_config.initial_prompt:
            msg += f"\nProject-specific instructions:\n {proj.project_config.initial_prompt}"

        self._project_prompt_status.mark_project_activation_message_as_provided(session_id)

        return msg

    def _refresh_active_state(self) -> None:
        """Atomically recompute modes and tools.

        This is the only path that both changes modes and recomputes tools.
        Callers must NOT call ``_update_active_modes()`` and
        ``_update_active_tools()`` separately — use this method instead
        to guarantee the tool set stays consistent with the current modes.
        """
        self._update_active_modes()
        self._update_active_tools()

    def _update_active_modes(self, log_message: bool = True) -> None:
        """
        Update active modes by delegating to ModeManager.refresh().

        Rebuilds the project config sources first (in case projects changed),
        then refreshes the mode resolution pipeline.
        """
        self._mode_manager.clear_project_configs()
        for project in self._project_manager.get_all().values():
            self._mode_manager.apply_project_config(project.project_config)
        self._mode_manager.refresh()
        if log_message:
            active_mode_names = self._mode_manager.get_mode_names()
            log.info(f"Active modes ({len(active_mode_names)}): {', '.join(active_mode_names)}")

    def _update_active_tools(self) -> None:
        """Update active tools by delegating to ToolManager.compute_active()."""
        self._tool_manager.compute_active(self._mode_manager.active_modes, self._project_manager)

    def issue_task(
        self,
        task: Callable[[], T],
        name: str | None = None,
        logged: bool = True,
        timeout: float | None = None,
        *,
        project: str | None = None,
        read_only: bool = False,
        session_id: str | None = None,
    ) -> TaskExecutor.Task[T]:
        """
        Issue a task to the executor for asynchronous execution.
        It is ensured that tasks are executed in the order they are issued, one after another.

        :param task: the task to execute
        :param name: the name of the task for logging purposes; if None, use the task function's name
        :param logged: whether to log management of the task; if False, only errors will be logged
        :param timeout: the maximum time to wait for task completion in seconds, or None to wait indefinitely
        :param project: Optional project name used to schedule per-project concurrency.
        :param read_only: Whether the task is read-only (allows parallelism with other read-only tasks on the same project).
        :param session_id: Optional session identifier for diagnostics.
        :return: the task object, through which the task's future result can be accessed
        """
        return self._task_executor.issue_task(
            task,
            name=name,
            logged=logged,
            timeout=timeout,
            project=project,
            read_only=read_only,
            session_id=session_id,
        )

    def execute_task(
        self,
        task: Callable[[], T],
        name: str | None = None,
        logged: bool = True,
        timeout: float | None = None,
        *,
        project: str | None = None,
        read_only: bool = False,
        session_id: str | None = None,
    ) -> T:
        """
        Executes the given task synchronously via the agent's task executor.
        This is useful for tasks that need to be executed immediately and whose results are needed right away.

        :param task: the task to execute
        :param name: the name of the task for logging purposes; if None, use the task function's name
        :param logged: whether to log management of the task; if False, only errors will be logged
        :param timeout: the maximum time to wait for task completion in seconds, or None to wait indefinitely
        :param project: Optional project name for concurrency scoping.
        :param read_only: Whether the task is read-only.
        :param session_id: Optional session identifier for diagnostics.
        :return: the result of the task execution
        """
        return self._task_executor.execute_task(
            task,
            name=name,
            logged=logged,
            timeout=timeout,
            project=project,
            read_only=read_only,
            session_id=session_id,
        )

    def is_using_language_server(self) -> bool:
        """
        :return: whether this agent uses language server-based code analysis
        """
        return self._language_backend == LanguageBackend.LSP

    def _remove_active_project(self, project_name: str) -> bool:
        """
        Remove a project from the active set and shut down its resources.
        Delegates to ProjectManager which handles session bindings and cleanup.

        :param project_name: the name of the project to remove
        :return: True if the project was removed, False if it wasn't active
        """
        return self._project_manager.remove(project_name)

    def activate_project_from_path_or_name(
        self, project_root_or_name: str
    ) -> bool:
        """
        Activate a project from a path or a name.

        Resolution is delegated to ProjectManager. If the project resolves,
        ``project.set_agent(self)`` is called before adding it to the active set.

        :param project_root_or_name: registered project name or filesystem path
        :return: True if the project was newly activated, False if it was already active
        :raises ProjectNotFoundError: if the project could neither be found nor created
        """
        project_instance = self._project_manager.resolve_project(project_root_or_name, self.serena_config)
        if project_instance is None:
            raise ProjectNotFoundError(
                f"Project '{project_root_or_name}' not found. "
                f"Existing project names: {self.serena_config.project_names}"
            )

        project_instance.set_agent(self)
        is_new = self._project_manager.add(project_instance)

        if is_new and self._project_activation_callback is not None:
            self._project_activation_callback()

        return is_new

    def get_active_tool_names(self) -> list[str]:
        """
        :return: the list of names of the active tools for the current project, sorted alphabetically
        """
        return self._tool_manager.active_tools.tool_names

    def tool_is_active(self, tool_name: str) -> bool:
        """
        :param tool_class: the name of the tool to check
        :return: True if the tool is active, False otherwise
        """
        return self._tool_manager.active_tools.contains_tool_name(tool_name)

    def tool_is_exposed(self, tool_name: str) -> bool:
        """
        :param tool_name: the name of the tool to check
        :return: True if the tool is in the exposed tool set, False otherwise
        """
        return self._tool_manager.exposed_tools.contains_tool_name(tool_name)

    def get_current_config_overview(self) -> str:
        """
        :return: a string overview of the current configuration, including the active and available configuration options
        """
        result_str = "Current configuration:\n"
        result_str += f"Serena version: {self.version}\n"
        result_str += f"Loglevel: {self.serena_config.log_level}, trace_lsp_communication={self.serena_config.trace_lsp_communication}\n"
        all_active = self._project_manager.get_all()
        if all_active:
            result_str += "Active projects: {}\n".format(", ".join(all_active.keys()))
        else:
            result_str += "No active projects\n"
        result_str += f"Language backend: {self._language_backend.value}"
        if all_active:
            first_project = next(iter(all_active.values()))
            if first_project.project_config.language_backend is not None:
                result_str += " (project override)"
        result_str += f" (global default: {self.serena_config.language_backend.value})\n"
        result_str += "Available projects:\n" + "\n".join(list(self.serena_config.project_names)) + "\n"
        result_str += f"Active context: {self._context.name}\n"

        # Active modes
        active_mode_names = [mode.name for mode in self.get_active_modes()]
        result_str += "Active modes: {}\n".format(", ".join(active_mode_names)) + "\n"

        # Available but not active modes
        all_available_modes = SerenaAgentMode.list_registered_mode_names()
        inactive_modes = [mode for mode in all_available_modes if mode not in active_mode_names]
        if inactive_modes:
            result_str += "Available but not active modes: {}\n".format(", ".join(inactive_modes)) + "\n"

        # Active tools
        result_str += "Active tools (after all exclusions from the project, context, and modes):\n"
        active_tool_names = self.get_active_tool_names()
        # print the tool names in chunks
        chunk_size = 4
        for i in range(0, len(active_tool_names), chunk_size):
            chunk = active_tool_names[i : i + chunk_size]
            result_str += "  " + ", ".join(chunk) + "\n"

        # Available but not active tools
        all_tool_names = sorted([tool.get_name_from_cls() for tool in self._tool_manager.all_tools.values()])
        inactive_tool_names = [tool for tool in all_tool_names if tool not in active_tool_names]
        if inactive_tool_names:
            result_str += "Available but not active tools:\n"
            for i in range(0, len(inactive_tool_names), chunk_size):
                chunk = inactive_tool_names[i : i + chunk_size]
                result_str += "  " + ", ".join(chunk) + "\n"

        return result_str

    def reset_language_server_manager(self, project_name: str | None = None) -> None:
        """
        Resets the language server manager for the given project or the context project.

        :param project_name: explicit project name, or None to use the tool execution context
        """
        project = self._resolve_project_for_action(project_name)
        project.create_language_server_manager()

    def add_language(self, language: Language, project_name: str | None = None) -> None:
        """
        Adds a new language to the given project, spawning the respective language server.

        :param language: the language to add
        :param project_name: explicit project name, or None to use the tool execution context
        """
        project = self._resolve_project_for_action(project_name)
        self.execute_task(lambda: project.add_language(language), name=f"AddLanguage:{language.value}")

    def remove_language(self, language: Language, project_name: str | None = None) -> None:
        """
        Removes a language from the given project.

        :param language: the language to remove
        :param project_name: explicit project name, or None to use the tool execution context
        """
        project = self._resolve_project_for_action(project_name)
        self.issue_task(lambda: project.remove_language(language), name=f"RemoveLanguage:{language.value}")

    def _resolve_project_for_action(self, project_name: str | None = None) -> Project:
        """Resolve a project for an action by name or tool execution context."""
        if project_name:
            proj = self._project_manager.get_by_name(project_name)
            if proj is None:
                raise ValueError(f"Project '{project_name}' is not active.")
            return proj
        from serena.tools.tools_base import _current_project

        proj = _current_project.get()
        if proj is not None:
            return proj
        first = next(iter(self._project_manager.get_all().values()), None)
        if first is None:
            raise ValueError("No active project.")
        return first

    def get_tool(self, tool_class: type[TTool]) -> TTool:
        return self._tool_manager.all_tools[tool_class]  # type: ignore

    def print_tool_overview(self) -> None:
        from serena.tools import ToolRegistry

        ToolRegistry().print_tool_overview(self._tool_manager.active_tools.tools)

    def _on_projects_changed(self) -> None:
        """Callback invoked by ProjectManager after any project is added or removed."""
        mode_names_before = set(self._mode_manager.get_mode_names()) if hasattr(self, '_mode_manager') else set()
        self._refresh_active_state()
        newly_activated = set(self._mode_manager.get_mode_names()) - mode_names_before
        self._project_prompt_status = ProjectPromptProvisionStatus(newly_activated_mode_names=newly_activated)
        # Notify dashboard manager of project change (for tray manager mode)
        dm = getattr(self, '_dashboard_manager', None)
        if dm is not None:
            first = next(iter(self._project_manager.get_all().values()), None)
            dm.update_active_project(first)

    def __del__(self) -> None:
        self.on_shutdown()

    def on_shutdown(self, timeout: float = 2.0) -> None:
        """
        Shutdown handler of the agent, freeing resources and stopping background tasks.
        """
        log.info("SerenaAgent is shutting down ...")
        # Shut down all projects via ProjectManager (guard for partial init failures)
        if hasattr(self, '_project_manager') and self._project_manager is not None:
            self._project_manager.shutdown_all(timeout=timeout)
        self._session_context_overrides.clear()
        has_session_manager = hasattr(self, '_session_manager') and self._session_manager is not None
        if has_session_manager:
            self._session_manager = SessionManager()
        if self._gui_log_viewer:
            log.info("Stopping the GUI log window ...")
            self._gui_log_viewer.stop()
            self._gui_log_viewer = None
        if hasattr(self, '_dashboard_manager') and self._dashboard_manager is not None:
            self._dashboard_manager.shutdown()
            self._dashboard_manager = None
        if hasattr(self, '_task_executor') and self._task_executor is not None:
            self._task_executor.shutdown()

    def shutdown(self) -> None:
        """
        Triggers a hard shutdown of the agent, freeing resources and signalling the process to terminate
        """
        # perform clean-up right away, because kill does not result in normal deletion of the object
        self.on_shutdown()

        # signal process termination
        os.kill(os.getpid(), signal.SIGTERM)

    def get_tool_by_name(self, tool_name: str) -> Tool:
        from serena.tools import ToolRegistry

        tool_class = ToolRegistry().get_tool_class_by_name(tool_name)
        return self.get_tool(tool_class)

    def get_active_lsp_languages(self) -> list[Language]:
        ls_manager = self.get_language_server_manager()
        if ls_manager is None:
            return []
        return ls_manager.get_active_languages()

    @contextmanager
    def active_project_context(self, project: Project) -> Iterator[None]:
        """
        Context manager for temporarily setting/overriding the project context.
        Delegates to ``project_context()`` from ``tools_base`` to set the
        thread-local ``_current_project`` variable.

        .. deprecated::
           Prefer ``project_context(project)`` from ``serena.tools.tools_base``
           for new code.
        """
        from serena.tools.tools_base import project_context

        with project_context(project):
            yield
