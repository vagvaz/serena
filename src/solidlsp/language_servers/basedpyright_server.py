"""
Python language server integration using basedpyright (a fork of pyright with additional features).

You can pass the following entries in ``ls_specific_settings["python_basedpyright"]``:
    - ls_path: Override the executable used to start basedpyright-langserver.
    - basedpyright_version: Override the pinned basedpyright version used with ``uvx`` / ``uv x``
      (default: the bundled Serena version).
"""

import logging
import os
import pathlib
import re
import shutil
import sys
import threading
from typing import cast

from typing_extensions import override

from solidlsp.ls import LanguageServerDependencyProvider, SolidLanguageServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)

BASEDPYRIGHT_VERSION = "1.38.4"


class BasedPyrightServer(SolidLanguageServer):
    """
    Provides Python specific instantiation of the LanguageServer class using basedpyright.
    """

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings):
        """
        Creates a BasedPyrightServer instance. This class is not meant to be instantiated directly.
        Use LanguageServer.create() instead.
        """
        super().__init__(
            config,
            repository_root_path,
            None,
            "python",
            solidlsp_settings,
        )

        self.analysis_complete = threading.Event()
        self.found_source_files = False

    def _create_dependency_provider(self) -> LanguageServerDependencyProvider:
        return self.DependencyProvider(self._custom_settings, self._ls_resources_dir)

    class DependencyProvider(LanguageServerDependencyProvider):
        def create_launch_command(self) -> list[str]:
            # respecting an explicit override
            ls_path = self._custom_settings.get("ls_path")
            if ls_path is not None:
                return [ls_path, "--stdio"]

            basedpyright_version = self._custom_settings.get("basedpyright_version", BASEDPYRIGHT_VERSION)

            # preferring uvx for on-demand execution
            uvx_path = os.environ.get("UVX") or shutil.which("uvx")
            if uvx_path is not None:
                return [uvx_path, "--from", f"basedpyright=={basedpyright_version}", "basedpyright-langserver", "--stdio"]

            # falling back to uv's uvx-compatible subcommand when only `uv` is available
            uv_path = shutil.which("uv")
            if uv_path is not None:
                return [uv_path, "x", "--from", f"basedpyright=={basedpyright_version}", "basedpyright-langserver", "--stdio"]

            # last resort: try to find basedpyright-langserver or basedpyright on PATH
            basedpyright_path = shutil.which("basedpyright-langserver")
            if basedpyright_path is not None:
                return [basedpyright_path, "--stdio"]

            # fallback to python module execution
            return [sys.executable, "-m", "basedpyright.langserver", "--stdio"]

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        return super().is_ignored_dirname(dirname) or dirname in ["venv", "__pycache__"]

    @override
    def _get_language_id_for_file(self, relative_file_path: str) -> str:
        return "python"

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        """
        Returns the initialize params for the BasedPyright Language Server.
        """
        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        initialize_params = {  # type: ignore
            "processId": os.getpid(),
            "clientInfo": {"name": "Serena", "version": "0.1.0"},
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "initializationOptions": {
                "exclude": [
                    "**/__pycache__",
                    "**/.venv",
                    "**/.env",
                    "**/build",
                    "**/dist",
                    "**/.pixi",
                ],
                "reportMissingImports": "error",
            },
            "capabilities": {
                "workspace": {
                    "workspaceEdit": {"documentChanges": True},
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    "didChangeWatchedFiles": {"dynamicRegistration": True},
                    "symbol": {
                        "dynamicRegistration": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                    },
                    "executeCommand": {"dynamicRegistration": True},
                },
                "textDocument": {
                    "synchronization": {
                        "dynamicRegistration": True,
                        "willSave": True,
                        "willSaveWaitUntil": True,
                        "didSave": True,
                    },
                    "hover": {"dynamicRegistration": True, "contentFormat": ["markdown", "plaintext"]},
                    "signatureHelp": {
                        "dynamicRegistration": True,
                        "signatureInformation": {
                            "documentationFormat": ["markdown", "plaintext"],
                            "parameterInformation": {"labelOffsetSupport": True},
                        },
                    },
                    "definition": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "documentSymbol": {
                        "dynamicRegistration": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                        "hierarchicalDocumentSymbolSupport": True,
                    },
                    "publishDiagnostics": {"relatedInformation": True},
                },
            },
            "workspaceFolders": [{"uri": root_uri, "name": os.path.basename(repository_absolute_path)}],
        }

        return cast(InitializeParams, initialize_params)

    def _start_server(self) -> None:
        """
        Starts the BasedPyright language server.
        """

        def execute_client_command_handler(params: dict) -> list:
            return []

        def do_nothing(params: dict) -> None:
            return

        def window_log_message(msg: dict) -> None:
            message_text = msg.get("message", "")
            log.info(f"LSP: window/logMessage: {message_text}")

            if re.search(r"Found \d+ source files?", message_text):
                log.info("basedpyright workspace scanning complete")
                self.found_source_files = True
                self.analysis_complete.set()

        def check_experimental_status(params: dict) -> None:
            if params.get("quiescent") == True:
                log.info("Received experimental/serverStatus with quiescent=true")
                if not self.found_source_files:
                    self.analysis_complete.set()

        self.server.on_request("client/registerCapability", do_nothing)
        self.server.on_notification("language/status", do_nothing)
        self.server.on_notification("window/logMessage", window_log_message)
        self.server.on_request("workspace/executeClientCommand", execute_client_command_handler)
        self.server.on_notification("$/progress", do_nothing)
        self.server.on_notification("textDocument/publishDiagnostics", do_nothing)
        self.server.on_notification("language/actionableNotification", do_nothing)
        self.server.on_notification("experimental/serverStatus", check_experimental_status)

        log.info("Starting basedpyright-langserver server process")
        self.server.start()

        initialize_params = self._get_initialize_params(self.repository_root_path)

        log.info("Sending initialize request from LSP client to basedpyright server and awaiting response")
        init_response = self.server.send.initialize(initialize_params)
        log.info(f"Received initialize response from basedpyright server: {init_response}")

        assert "textDocumentSync" in init_response["capabilities"]
        assert "completionProvider" in init_response["capabilities"]
        assert "definitionProvider" in init_response["capabilities"]

        self.server.notify.initialized({})

        log.info("Waiting for basedpyright to complete initial workspace analysis...")
        if self.analysis_complete.wait(timeout=5.0):
            log.info("basedpyright initial analysis complete, server ready")
        else:
            log.warning("Timeout waiting for basedpyright analysis completion, proceeding anyway")
            self.analysis_complete.set()
