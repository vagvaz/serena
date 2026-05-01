"""
Mode lifecycle management for SerenaAgent.

Provides ActiveModes and ModeManager — extracting mode resolution logic
(global config → project configs → session definition → overrides) from
agent.py into a dedicated module.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from serena.config.context_mode import SerenaAgentMode
    from serena.config.serena_config import (
        ModeSelectionDefinition,
        ProjectConfig,
        SerenaConfig,
    )

log = logging.getLogger(__name__)


class ActiveModes:
    """Resolved set of active modes, computed from multiple ModeSelectionDefinition sources."""

    _mode_instances: dict[str, SerenaAgentMode] = {}

    def __init__(self) -> None:
        self._configured_base_modes: Sequence[str] | None = None
        self._configured_default_modes: Sequence[str] | None = None
        self._added_modes: set[str] = set()
        self._dynamically_activated_mode_names: set[str] = set()
        self._active_mode_names: Sequence[str] = []

    def apply(self, mode_selection: ModeSelectionDefinition) -> None:
        """Apply a mode selection definition, accumulating base/default/added modes."""
        log.debug("Applying mode selection definition %s", mode_selection)

        from serena.config.serena_config import (
            ModeSelectionDefinitionWithAddedModes,
            ModeSelectionDefinitionWithBaseModes,
        )

        if isinstance(mode_selection, ModeSelectionDefinitionWithBaseModes):
            if mode_selection.base_modes is not None:
                self._configured_base_modes = mode_selection.base_modes
        if mode_selection.default_modes is not None:
            self._configured_default_modes = mode_selection.default_modes
        log.debug(
            "Current mode selection: base_modes=%s, default_modes=%s",
            self._configured_base_modes,
            self._configured_default_modes,
        )

        if isinstance(mode_selection, ModeSelectionDefinitionWithAddedModes):
            if mode_selection.added_modes:
                log.debug("Adding modes: %s", mode_selection.added_modes)
                self._added_modes.update(mode_selection.added_modes)
                log.debug("Current added modes: %s", self._added_modes)

        self._dynamically_activated_mode_names = set(self._configured_default_modes or []) | self._added_modes
        self._active_mode_names = sorted(set(self._configured_base_modes or []) | self._dynamically_activated_mode_names)

    def get_mode_names(self) -> Sequence[str]:
        return self._active_mode_names

    @classmethod
    def get_mode_instance(cls, mode_name: str) -> SerenaAgentMode:
        if mode_name not in cls._mode_instances:
            from serena.config.context_mode import SerenaAgentMode

            cls._mode_instances[mode_name] = SerenaAgentMode.load(mode_name)
        return cls._mode_instances[mode_name]

    def get_modes(self) -> Sequence[SerenaAgentMode]:
        return [self.get_mode_instance(mode_name) for mode_name in self._active_mode_names]

    def get_dynamically_activated_modes(self) -> Sequence[SerenaAgentMode]:
        return [self.get_mode_instance(mode_name) for mode_name in self._dynamically_activated_mode_names]

    def get_base_modes(self) -> Sequence[SerenaAgentMode]:
        return [self.get_mode_instance(mode_name) for mode_name in self._configured_base_modes or []]


class ModeManager:
    """
    Manages the mode resolution pipeline for SerenaAgent.

    Modes are resolved from multiple sources in order (later sources override
    or extend earlier ones):

        1. Global Serena config (always present)
        2. Per-project configs (0 or more active projects)
        3. Session definition (CLI ``--mode`` / ``--add-mode``)
        4. Dynamic overrides (tool calls, if any)

    Usage::

        mgr = ModeManager()
        mgr.apply_config(serena_config)
        for pc in project_configs:
            mgr.apply_project_config(pc)
        mgr.apply_session_definition(session_def)
        mgr.refresh()
        modes = mgr.active_modes      # → ActiveModes instance
    """

    def __init__(self) -> None:
        self._active_modes = ActiveModes()
        self._config: SerenaConfig | None = None
        self._project_configs: list[ProjectConfig] = []
        self._session_definition: ModeSelectionDefinition | None = None
        self._overrides: ModeSelectionDefinition | None = None

    # ── Source registration ─────────────────────────────────────────

    def apply_config(self, config: SerenaConfig) -> None:
        """Register the global Serena configuration as a mode source."""
        self._config = config

    def apply_project_config(self, config: ProjectConfig) -> None:
        """Register a per-project config as a mode source."""
        self._project_configs.append(config)

    def clear_project_configs(self) -> None:
        """Clear all per-project configs (e.g. when project set changes)."""
        self._project_configs.clear()

    def apply_session_definition(self, definition: ModeSelectionDefinition | None) -> None:
        """Register the per-session mode selection definition (from CLI args)."""
        self._session_definition = definition

    def apply_overrides(self, overrides: ModeSelectionDefinition | None) -> None:
        """Register dynamic mode overrides (e.g. from a tool call)."""
        self._overrides = overrides

    # ── Refresh ─────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Recompute active modes from all registered sources."""
        self._active_modes = ActiveModes()

        # 1. Global config
        if self._config is not None:
            self._active_modes.apply(self._config)

        # 2. Per-project configs
        for pc in self._project_configs:
            self._active_modes.apply(pc)

        # 3. Session definition (CLI --mode / --add-mode)
        if self._session_definition is not None:
            self._active_modes.apply(self._session_definition)

        # 4. Dynamic overrides
        if self._overrides is not None:
            self._active_modes.apply(self._overrides)

        log.info(
            "Active modes (%d): %s",
            len(self._active_modes.get_mode_names()),
            ", ".join(self._active_modes.get_mode_names()),
        )

    # ── Read access ─────────────────────────────────────────────────

    @property
    def active_modes(self) -> ActiveModes:
        return self._active_modes

    def get_mode_names(self) -> Sequence[str]:
        return self._active_modes.get_mode_names()

    def get_mode_instances(self) -> Sequence[SerenaAgentMode]:
        return self._active_modes.get_modes()

    def get_dynamically_activated_modes(self) -> Sequence[SerenaAgentMode]:
        return self._active_modes.get_dynamically_activated_modes()

    def get_base_modes(self) -> Sequence[SerenaAgentMode]:
        return self._active_modes.get_base_modes()

    def mode_names_changed_since(self, previous: set[str]) -> set[str]:
        """Return mode names that are newly active compared to *previous*."""
        return set(self._active_modes.get_mode_names()) - previous
