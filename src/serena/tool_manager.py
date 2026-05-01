"""
Tool lifecycle management for SerenaAgent.

Provides ToolSet, AvailableTools, and ToolManager — extracting the three-phase
tool lifecycle (registration → exposure → activation) from agent.py into a
dedicated module for locality and testability.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from serena.util.inspection import iter_subclasses

from serena.config.serena_config import (
    LanguageBackend,
    NamedToolInclusionDefinition,
    ToolInclusionDefinition,
)

if TYPE_CHECKING:
    from serena.agent import ActiveModes, SerenaAgent
    from serena.config.context_mode import SerenaAgentContext, SerenaAgentMode
    from serena.config.serena_config import SerenaConfig
    from serena.project import Project
    from serena.project_manager import ProjectManager
    from serena.tools import Tool
    from serena.tools.tools_base import ToolMarker

log = logging.getLogger(__name__)


class AvailableTools:
    """
    Represents the set of available/exposed tools of a SerenaAgent.
    """

    def __init__(self, tools: list[Tool]):
        """
        :param tools: the list of available tools
        """
        self.tools = tools
        self.tool_names = sorted([tool.get_name_from_cls() for tool in tools])
        """
        the list of available tool names, sorted alphabetically
        """
        self._tool_name_set = set(self.tool_names)
        self.tool_marker_names = set()
        from serena.tools.tools_base import ToolMarker

        for marker_class in iter_subclasses(ToolMarker):
            for tool in tools:
                if isinstance(tool, marker_class):
                    self.tool_marker_names.add(marker_class.__name__)

    def __len__(self) -> int:
        return len(self.tools)

    def contains_tool_name(self, tool_name: str) -> bool:
        return tool_name in self._tool_name_set

    def contains_tool_class(self, tool_class: type[Tool]) -> bool:
        return self.contains_tool_name(tool_class.get_name_from_cls())


class ToolSet:
    """
    Represents a set of tools by their names.
    """

    def __init__(self, tool_names: set[str]) -> None:
        self._tool_names = tool_names

    def __len__(self) -> int:
        return len(self._tool_names)

    @classmethod
    def default(cls) -> "ToolSet":
        """
        :return: the default tool set, which contains all tools that are enabled by default
        """
        # late import avoids circular dependency
        from serena.tools import ToolRegistry

        return cls(set(ToolRegistry().get_tool_names_default_enabled()))

    def apply(self, *tool_inclusion_definitions: ToolInclusionDefinition) -> "ToolSet":
        """
        Applies one or more tool inclusion definitions to this tool set,
        resulting in a new tool set.

        :param tool_inclusion_definitions: the definitions to apply
        :return: a new tool set with the definitions applied
        """
        # late import avoids circular dependency
        from serena.tools import ToolRegistry
        from serena.tools.file_tools import ReplaceContentTool

        LEGACY_TOOL_NAME_MAPPING = {"replace_regex": ReplaceContentTool.get_name_from_cls()}

        def get_updated_tool_name(tool_name: str) -> str:
            """Retrieves the updated tool name if the provided tool name is deprecated, logging a warning."""
            if tool_name in LEGACY_TOOL_NAME_MAPPING:
                new_tool_name = LEGACY_TOOL_NAME_MAPPING[tool_name]
                log.warning("Tool name '%s' is deprecated, please use '%s' instead", tool_name, new_tool_name)
                return new_tool_name
            return tool_name

        registry = ToolRegistry()
        tool_names = set(self._tool_names)
        for definition in tool_inclusion_definitions:
            if definition.is_fixed_tool_set():
                tool_names = set()
                for fixed_tool in definition.fixed_tools:
                    fixed_tool = get_updated_tool_name(fixed_tool)
                    if registry.check_valid_tool_name(fixed_tool, " (in fixed tools set)"):
                        tool_names.add(fixed_tool)
                log.info(f"{definition} defined a fixed tool set with {len(tool_names)} tools: {', '.join(tool_names)}")
            else:
                included_tools = []
                excluded_tools = []
                for included_tool in definition.included_optional_tools:
                    included_tool = get_updated_tool_name(included_tool)
                    if registry.check_valid_tool_name(included_tool, " (in included optional tools)") and included_tool not in tool_names:
                        tool_names.add(included_tool)
                        included_tools.append(included_tool)
                for excluded_tool in definition.excluded_tools:
                    excluded_tool = get_updated_tool_name(excluded_tool)
                    registry.check_valid_tool_name(excluded_tool, " (in excluded tools)")
                    if excluded_tool in tool_names:
                        tool_names.remove(excluded_tool)
                        excluded_tools.append(excluded_tool)
                if included_tools:
                    log.info(f"{definition} included {len(included_tools)} tools: {', '.join(included_tools)}")
                if excluded_tools:
                    log.info(f"{definition} excluded {len(excluded_tools)} tools: {', '.join(excluded_tools)}")
        return ToolSet(tool_names)

    def without_editing_tools(self) -> "ToolSet":
        """
        :return: a new tool set that excludes all tools that can edit
        """
        # late import avoids circular dependency
        from serena.tools import ToolRegistry

        registry = ToolRegistry()
        tool_names = set(self._tool_names)
        for tool_name in self._tool_names:
            if registry.get_tool_class_by_name(tool_name).can_edit():
                tool_names.remove(tool_name)
        return ToolSet(tool_names)

    def get_tool_names(self) -> set[str]:
        """
        Returns the names of the tools that are currently included in the tool set.
        """
        return self._tool_names

    def includes_name(self, tool_name: str) -> bool:
        return tool_name in self._tool_names

    def to_available_tools(self, all_tools: dict[type[Tool], Tool]) -> AvailableTools:
        return AvailableTools([t for t in all_tools.values() if self.includes_name(t.get_name())])


class ToolManager:
    """
    Three-phase tool lifecycle for SerenaAgent.

    Usage::

        manager = ToolManager()
        manager.register_all(agent)           # Phase 1: discover & instantiate
        manager.compute_base(config, ...)     # Phase 2: context-dependent filtering
        manager.compute_active(modes, pm)     # Phase 3: mode + project filtering
    """

    def __init__(self) -> None:
        self._all_tools: dict[type[Tool], Tool] = {}
        self._base_toolset: ToolSet = ToolSet.default()
        self._exposed_tools: AvailableTools = AvailableTools([])
        self._active_tools: AvailableTools = AvailableTools([])

    # ── Phase 1: Registration ───────────────────────────────────────

    def register_all(self, agent: SerenaAgent) -> list[str]:
        """Discover and instantiate all tool classes via ToolRegistry.

        :param agent: the agent instance to pass to each Tool constructor
        :returns: list of tool names that were loaded
        """
        from serena.tools import ToolRegistry

        self._all_tools = {
            tool_class: tool_class(agent)
            for tool_class in ToolRegistry().get_all_tool_classes()
        }
        return [tool.get_name_from_cls() for tool in self._all_tools.values()]

    # ── Phase 2: Base toolset (exposure) ────────────────────────────

    def compute_base(
        self,
        serena_config: SerenaConfig,
        language_backend: LanguageBackend,
        context: SerenaAgentContext,
        active_modes: ActiveModes,
        project: Project | None,
    ) -> None:
        """Compute the exposed tool set from config, context, modes, and project.

        The result is available via :attr:`exposed_tools` and :attr:`base_toolset`.
        """
        from serena.tools.config_tools import (
            ActivateProjectTool,
            DeactivateProjectTool,
            GetCurrentConfigTool,
            GetProjectStatusTool,
            ListActiveProjectsTool,
            OpenDashboardTool,
            SetSessionProjectTool,
        )
        from serena.config.context_mode import SerenaAgentMode

        tool_inclusion_definitions: list[ToolInclusionDefinition] = []

        # --- dashboard trigger for OpenDashboardTool ---
        if serena_config.web_dashboard and not serena_config.web_dashboard_open_on_launch and not serena_config.gui_log_window:
            tool_inclusion_definitions.append(
                NamedToolInclusionDefinition(
                    name="OpenDashboard",
                    included_optional_tools=[OpenDashboardTool.get_name_from_cls()],
                )
            )

        # --- serena config and context ---
        tool_inclusion_definitions.append(serena_config)
        tool_inclusion_definitions.append(context)

        # --- single-project mode ---
        is_single_project = context.single_project and project is not None

        # --- base modes ---
        for base_mode in active_modes.get_base_modes():
            tool_inclusion_definitions.append(base_mode)

        # --- dynamically activated modes ---
        for mode in active_modes.get_dynamically_activated_modes():
            if is_single_project:
                tool_inclusion_definitions.append(mode)
            else:
                tool_inclusion_definitions.append(
                    NamedToolInclusionDefinition(
                        name=f"InitialDynamicModeInclusions[{mode.name}]",
                        included_optional_tools=mode.included_optional_tools,
                    )
                )

        # --- single-project exclusions ---
        if is_single_project:
            assert project is not None
            log.info(
                "Applying tool inclusion/exclusion definitions for single-project context based on project '%s'",
                project.project_name,
            )
            tool_inclusion_definitions.append(
                NamedToolInclusionDefinition(
                    name="SingleProjectExclusions",
                    excluded_tools=[
                        ActivateProjectTool.get_name_from_cls(),
                        DeactivateProjectTool.get_name_from_cls(),
                        SetSessionProjectTool.get_name_from_cls(),
                        ListActiveProjectsTool.get_name_from_cls(),
                        GetProjectStatusTool.get_name_from_cls(),
                        GetCurrentConfigTool.get_name_from_cls(),
                    ],
                )
            )
            tool_inclusion_definitions.append(project.project_config)

        # --- JetBrains mode ---
        if language_backend == LanguageBackend.JETBRAINS:
            tool_inclusion_definitions.append(SerenaAgentMode.from_name_internal("jetbrains"))

        # --- apply all definitions ---
        tool_set = ToolSet.default()
        for definition in tool_inclusion_definitions:
            tool_set = tool_set.apply(definition)

        self._base_toolset = tool_set
        self._exposed_tools = tool_set.to_available_tools(self._all_tools)
        log.info(f"Number of exposed tools: {len(self._exposed_tools)}. Exposed tools: {self._exposed_tools.tool_names}")

    # ── Phase 3: Active tools ───────────────────────────────────────

    def compute_active(
        self,
        active_modes: ActiveModes,
        project_manager: ProjectManager,
    ) -> None:
        """Compute the active tool set from base + active modes + active projects.

        The result is available via :attr:`active_tools`.
        """
        tool_set = self._base_toolset.apply(*active_modes.get_modes())
        for project in project_manager.get_all().values():
            tool_set = tool_set.apply(project.project_config)
            if project.project_config.read_only:
                tool_set = tool_set.without_editing_tools()
        self._active_tools = tool_set.to_available_tools(self._all_tools)
        log.info(f"Active tools ({len(self._active_tools)}): {', '.join(self._active_tools.tool_names)}")

        # warn about exposed mismatches
        active_tools_not_exposed = set(self._active_tools.tool_names) - set(self._exposed_tools.tool_names)
        if active_tools_not_exposed:
            log.warning(
                "The following active tools are not in the exposed tool set and thus won't be available to clients:\n"
                f"{active_tools_not_exposed}\n"
                "Consider adjusting your configuration to include these tools if you want to use them."
            )

    # ── Read access ─────────────────────────────────────────────────

    @property
    def all_tools(self) -> dict[type[Tool], Tool]:
        return self._all_tools

    @property
    def base_toolset(self) -> ToolSet:
        return self._base_toolset

    @property
    def exposed_tools(self) -> AvailableTools:
        return self._exposed_tools

    @property
    def active_tools(self) -> AvailableTools:
        return self._active_tools
