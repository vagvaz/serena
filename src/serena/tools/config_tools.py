from serena.util.misc import mark_used

from serena.tools import Tool, ToolMarkerDoesNotRequireActiveProject, ToolMarkerOptional


class OpenDashboardTool(Tool, ToolMarkerOptional, ToolMarkerDoesNotRequireActiveProject):
    """
    Opens the Serena web dashboard in the default web browser.
    The dashboard provides logs, session information, and tool usage statistics.
    """

    def apply(self) -> str:
        """
        Opens the Serena web dashboard in the default web browser.
        """
        if self.agent.open_dashboard():
            return f"Serena web dashboard has been opened in the user's default web browser: {self.agent.get_dashboard_url()}"
        else:
            return f"Serena web dashboard could not be opened automatically; tell the user to open it via {self.agent.get_dashboard_url()}"


class RestartDashboardTool(Tool, ToolMarkerDoesNotRequireActiveProject):
    """
    Restarts the dashboard web server without affecting LSP processes or tool execution.
    Useful after modifying dashboard templates, CSS, or Python code.
    """

    def apply(self) -> str:
        """
        Restarts the dashboard web server.
        """
        return self.agent.restart_dashboard()


class ActivateProjectTool(Tool, ToolMarkerDoesNotRequireActiveProject):
    """
    Activates a project based on the project name or path.
    In multi-project mode, this adds the project to the active set without
    deactivating other projects.
    """

    # noinspection PyIncorrectDocstring
    # (session_id is injected via apply_ex)
    def apply(self, project: str, session_id: str) -> str:
        """
        Activates the project with the given name or path. If the project is already
        active, this is a no-op. Other active projects remain active.

        :param project: the name of a registered project to activate or a path to a project directory
        """
        from serena.tools.tools_base import get_current_session_id

        is_new_activation = self.agent.activate_project_from_path_or_name(project)
        if not is_new_activation:
            result = "Project was already active."
        else:
            # Find the activated project to generate the activation message
            all_active = self.agent.get_all_active_projects()
            active_project = next(iter(all_active.values())) if all_active else None
            session_id = get_current_session_id()
            result = self.agent._get_project_activation_message(active_project, session_id=session_id) if active_project else "Project activated."
            # Bind the current session to the newly activated project
            session_id = get_current_session_id()
            if session_id and active_project:
                self.agent.get_session_manager().set_project(session_id, active_project.project_name)
        result += "\nIMPORTANT: If you have not yet read the 'Serena Instructions Manual', do it now before continuing!"
        return result


class SetSessionProjectTool(Tool, ToolMarkerDoesNotRequireActiveProject):
    """
    Sets the project binding for the current session.
    Accepts either a registered project name or a filesystem path to a project root.
    """

    def apply(self, project: str) -> str:
        """
        Sets the project binding for the current session.
        The project can be specified as either a registered project name or a path to a project directory.
        This does NOT activate the project globally — it only binds the current session to it.
        If the project is not already active, it will be activated first.

        :param project: the name of a registered project or a path to a project directory
        """
        from serena.tools.tools_base import get_current_session_id

        session_id = get_current_session_id()
        if session_id is None:
            return "Error: Setting session project requires an MCP connection context."

        # Try to activate the project if not already active
        try:
            was_new = self.agent.activate_project_from_path_or_name(project)
        except Exception as exc:
            return f"Error: Failed to activate project '{project}': {exc}"

        # Resolve the canonical project name
        project_instance = self.agent.serena_config.get_project(project)
        if project_instance is None:
            project_instance = self.agent.resolve_project_for_path(project)
        if project_instance is None:
            return f"Error: Could not resolve project from '{project}'."

        canonical_name = project_instance.project_name
        self.agent.get_session_manager().set_project(session_id, canonical_name)

        msg = f"Session bound to project '{canonical_name}'."
        if was_new:
            msg += " Project was activated."
        return msg


class DeactivateProjectTool(Tool, ToolMarkerDoesNotRequireActiveProject, ToolMarkerOptional):
    """
    Deactivates a project, shutting down its language server and freeing resources.
    """

    def apply(self, project: str) -> str:
        """
        Deactivates the project with the given name or path, shutting down its language server
        and freeing resources. Other active projects remain active.

        :param project: the name of the project to deactivate
        """
        # Resolve project name
        project_name = project
        active_projects = self.agent.get_all_active_projects()
        if project_name not in active_projects:
            # Try to find by path prefix
            for name, proj in active_projects.items():
                if project in proj.project_root:
                    project_name = name
                    break
            else:
                return f"Error: Project '{project}' is not active. Active projects: {', '.join(active_projects.keys())}"

        success = self.agent._remove_active_project(project_name)
        if success:
            return f"Project '{project_name}' has been deactivated and its resources freed."
        else:
            return f"Error: Project '{project_name}' was not active."


class ListActiveProjectsTool(Tool, ToolMarkerDoesNotRequireActiveProject, ToolMarkerOptional):
    """
    Lists all currently active projects with their status.
    """

    def apply(self) -> str:
        """
        Lists all currently active projects with their status including name, path,
        languages, LSP status, and idle time.
        """
        import time

        active = self.agent.get_all_active_projects()
        if not active:
            return "No projects are currently active."

        lines = ["Active projects:"]
        for name, project in active.items():
            languages = ", ".join(lang.value for lang in project.project_config.languages)
            ls_manager = project.language_server_manager
            lsp_status = "running" if ls_manager and ls_manager.is_running() else "not running"
            last_active = self.agent._project_manager.get_last_active_timestamp(name)
            if last_active:
                idle_seconds = time.time() - last_active
                idle_str = f"{idle_seconds:.0f}s ago"
            else:
                idle_str = "unknown"
            lines.append(f"  - {name}: {project.project_root}")
            lines.append(f"    Languages: {languages}, LSP: {lsp_status}, Last active: {idle_str}")

        return "\n".join(lines)


class GetProjectStatusTool(Tool, ToolMarkerDoesNotRequireActiveProject, ToolMarkerOptional):
    """
    Gets detailed status of a specific project.
    """

    def apply(self, project: str) -> str:
        """
        Gets detailed status of the specified project including activation state,
        LSP status, idle time, and memory count.

        :param project: the name of the project to check status for
        """
        import time

        active_projects = self.agent.get_all_active_projects()
        project_obj = active_projects.get(project)

        if project_obj is None:
            # Check if it's a registered but not active project
            registered = self.agent.serena_config.get_registered_project(project, autoregister=False)
            if registered:
                return f"Project '{project}' is registered but not currently active."
            return f"Error: Project '{project}' not found in registered projects."

        lines = [f"Project: {project_obj.project_name}"]
        lines.append(f"  Path: {project_obj.project_root}")
        languages = ", ".join(lang.value for lang in project_obj.project_config.languages)
        lines.append(f"  Languages: {languages}")
        lines.append(f"  Status: active")

        ls_manager = project_obj.language_server_manager
        if ls_manager:
            lsp_running = ls_manager.is_running()
            lines.append(f"  LSP: {'running' if lsp_running else 'not running'}")
            if lsp_running:
                active_langs = ls_manager.get_active_languages()
                lines.append(f"  Active LSP languages: {', '.join(lang.value for lang in active_langs)}")

        last_active = self.agent._project_manager.get_last_active_timestamp(project)
        if last_active:
            idle_seconds = time.time() - last_active
            lines.append(f"  Last active: {idle_seconds:.0f}s ago")

        memories = project_obj.memories_manager.list_project_memories()
        lines.append(f"  Memories: {len(memories)}")

        return "\n".join(lines)


class RemoveProjectTool(Tool, ToolMarkerDoesNotRequireActiveProject, ToolMarkerOptional):
    """
    Removes a project from the Serena configuration.
    """

    def apply(self, project_name: str) -> str:
        """
        Removes a project from the Serena configuration.

        :param project_name: Name of the project to remove
        """
        self.agent.serena_config.remove_project(project_name)
        return f"Successfully removed project '{project_name}' from configuration."


class GetCurrentConfigTool(Tool):
    """
    Prints the current configuration of the agent, including the active and available projects, tools, contexts, and modes.
    """

    def apply(self) -> str:
        """
        Print the current configuration of the agent, including the active and available projects, tools, contexts, and modes.
        """
        return self.agent.get_current_config_overview()
