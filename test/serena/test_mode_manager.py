"""Tests for ModeManager and ActiveModes — mode resolution pipeline."""

from unittest.mock import MagicMock

import pytest

from serena.config.serena_config import (
    ModeSelectionDefinition,
    ModeSelectionDefinitionWithAddedModes,
    ModeSelectionDefinitionWithBaseModes,
)
from serena.mode_manager import ActiveModes, ModeManager


def _config_mock(default_modes=None, base_modes=None):
    """Create a ModeSelectionDefinitionWithBaseModes that passes isinstance checks."""
    return ModeSelectionDefinitionWithBaseModes(
        default_modes=default_modes,
        base_modes=base_modes,
    )


# ── ActiveModes ──────────────────────────────────────────────────────

class TestActiveModes:
    def test_empty_on_init(self):
        modes = ActiveModes()
        assert modes.get_mode_names() == []
        assert modes.get_modes() == []
        assert modes.get_base_modes() == []
        assert modes.get_dynamically_activated_modes() == []

    def test_apply_config_sets_default_modes(self):
        config = _config_mock(default_modes=["editing", "interactive"])

        modes = ActiveModes()
        modes.apply(config)
        assert "editing" in modes.get_mode_names()
        assert "interactive" in modes.get_mode_names()

    def test_apply_config_sets_base_modes(self):
        config = _config_mock(default_modes=None, base_modes=["base-mode"])

        modes = ActiveModes()
        modes.apply(config)
        assert "base-mode" in modes.get_mode_names()

    def test_default_modes_override_previous(self):
        config1 = _config_mock(default_modes=["editing"])
        config2 = _config_mock(default_modes=["planning"])

        modes = ActiveModes()
        modes.apply(config1)
        modes.apply(config2)
        names = modes.get_mode_names()
        assert "editing" not in names
        assert "planning" in names

    def test_base_modes_persist_across_applies(self):
        with_mode = _config_mock(default_modes=None, base_modes=["base-mode"])
        without = _config_mock(default_modes=None, base_modes=None)

        modes = ActiveModes()
        modes.apply(with_mode)
        modes.apply(without)
        assert "base-mode" in modes.get_mode_names()

    def test_added_modes_accumulate(self):
        base = _config_mock(default_modes=["editing"])
        added = ModeSelectionDefinitionWithAddedModes(
            default_modes=None, added_modes=["my-mode"]
        )

        modes = ActiveModes()
        modes.apply(base)
        modes.apply(added)
        assert "my-mode" in modes.get_mode_names()
        assert "editing" in modes.get_mode_names()

    def test_get_modes_returns_mode_instances(self):
        config = _config_mock(default_modes=["planning"])

        modes = ActiveModes()
        modes.apply(config)
        instances = modes.get_modes()
        assert len(instances) == 1
        assert instances[0].name == "planning"

    def test_mode_instances_are_cached(self):
        config = _config_mock(default_modes=["planning"])

        modes = ActiveModes()
        modes.apply(config)
        i1 = modes.get_mode_instance("planning")
        i2 = modes.get_mode_instance("planning")
        assert i1 is i2


# ── ModeManager ──────────────────────────────────────────────────────

class TestModeManager:
    def test_empty_on_init(self):
        mgr = ModeManager()
        assert mgr.get_mode_names() == []

    def test_refresh_with_config_only(self):
        mgr = ModeManager()
        config = _config_mock(default_modes=["editing"])
        mgr.apply_config(config)
        mgr.refresh()
        assert "editing" in mgr.get_mode_names()

    def test_project_configs_merged(self):
        mgr = ModeManager()
        config = _config_mock(default_modes=["editing"])
        mgr.apply_config(config)

        pc = _config_mock(default_modes=["planning"])
        mgr.apply_project_config(pc)

        mgr.refresh()
        names = mgr.get_mode_names()
        assert "editing" not in names  # overridden by project
        assert "planning" in names

    def test_session_definition_applied(self):
        mgr = ModeManager()
        config = _config_mock(default_modes=["editing"])
        mgr.apply_config(config)

        session = _config_mock(default_modes=["planning"])
        mgr.apply_session_definition(session)

        mgr.refresh()
        names = mgr.get_mode_names()
        assert "planning" in names

    def test_clear_project_configs(self):
        mgr = ModeManager()
        config = _config_mock(default_modes=["editing"])
        mgr.apply_config(config)

        pc = _config_mock(default_modes=["planning"])
        mgr.apply_project_config(pc)
        mgr.clear_project_configs()

        mgr.refresh()
        assert "editing" in mgr.get_mode_names()
        assert "planning" not in mgr.get_mode_names()

    def test_mode_names_changed_since(self):
        mgr = ModeManager()
        config = _config_mock(default_modes=["editing"])
        mgr.apply_config(config)
        mgr.refresh()

        prev = set(mgr.get_mode_names())
        config2 = _config_mock(default_modes=["editing", "planning"])
        mgr.apply_config(config2)
        mgr.refresh()

        changed = mgr.mode_names_changed_since(prev)
        assert "planning" in changed
        assert "editing" not in changed

    def test_multiple_project_configs(self):
        mgr = ModeManager()
        config = _config_mock(default_modes=[])
        mgr.apply_config(config)

        pc1 = _config_mock(default_modes=["mode-a"])
        mgr.apply_project_config(pc1)

        pc2 = _config_mock(default_modes=["mode-b"])
        mgr.apply_project_config(pc2)

        mgr.refresh()
        names = mgr.get_mode_names()
        assert "mode-b" in names  # second project overrides first
        assert "mode-a" not in names
