"""Tests for ToolManager, ToolSet, and AvailableTools — tool lifecycle."""

from unittest.mock import MagicMock, patch

import pytest

from serena.tool_manager import AvailableTools, ToolSet
from serena.tools import Tool


# Use a real tool name from the registry for tests that need tool validation
_VALID_TOOL_NAME = "read_file"


# ── ToolSet ──────────────────────────────────────────────────────────

class TestToolSet:
    def test_default_contains_tools(self):
        ts = ToolSet.default()
        assert len(ts) > 0

    def test_empty_toolset(self):
        ts = ToolSet(set())
        assert len(ts) == 0

    def test_apply_includes_optional_tools(self):
        ts = ToolSet(set())
        definition = MagicMock()
        definition.is_fixed_tool_set.return_value = False
        definition.included_optional_tools = [_VALID_TOOL_NAME]
        definition.excluded_tools = []

        ts2 = ts.apply(definition)
        assert _VALID_TOOL_NAME in ts2.get_tool_names()

    def test_apply_excludes_tools(self):
        ts = ToolSet({_VALID_TOOL_NAME, "find_symbol"})
        definition = MagicMock()
        definition.is_fixed_tool_set.return_value = False
        definition.included_optional_tools = []
        definition.excluded_tools = [_VALID_TOOL_NAME]

        ts2 = ts.apply(definition)
        assert _VALID_TOOL_NAME not in ts2.get_tool_names()
        assert "find_symbol" in ts2.get_tool_names()

    def test_fixed_tool_set_replaces_all(self):
        ts = ToolSet({_VALID_TOOL_NAME, "find_symbol"})
        definition = MagicMock()
        definition.is_fixed_tool_set.return_value = True
        definition.fixed_tools = [_VALID_TOOL_NAME]

        ts2 = ts.apply(definition)
        assert ts2.get_tool_names() == {_VALID_TOOL_NAME}

    def test_without_editing_tools(self):
        ts = ToolSet({"find_symbol", "replace_content"})
        assert hasattr(ts, "without_editing_tools")

    def test_includes_name(self):
        ts = ToolSet({_VALID_TOOL_NAME, "find_symbol"})
        assert ts.includes_name(_VALID_TOOL_NAME)
        assert not ts.includes_name("nonexistent")

    def test_to_available_tools_filters_dict(self):
        ts = ToolSet({"tool_a"})
        tool_a = MagicMock(spec=Tool)
        tool_a.get_name.return_value = "tool_a"
        tool_b = MagicMock(spec=Tool)
        tool_b.get_name.return_value = "tool_b"

        all_tools = {type(tool_a): tool_a, type(tool_b): tool_b}
        available = ts.to_available_tools(all_tools)
        assert len(available) == 1
        assert available.tools[0].get_name() == "tool_a"


# ── AvailableTools ───────────────────────────────────────────────────

class TestAvailableTools:
    def test_empty(self):
        at = AvailableTools([])
        assert len(at) == 0

    def test_single_tool(self):
        tool = MagicMock(spec=Tool)
        tool.get_name_from_cls.return_value = "my_tool"

        at = AvailableTools([tool])
        assert len(at) == 1
        assert "my_tool" in at.tool_names

    def test_contains_tool_name(self):
        tool = MagicMock(spec=Tool)
        tool.get_name_from_cls.return_value = "my_tool"

        at = AvailableTools([tool])
        assert at.contains_tool_name("my_tool")
        assert not at.contains_tool_name("other")

    def test_contains_tool_class(self):
        class FakeTool(Tool):
            @classmethod
            def get_name_from_cls(cls):
                return "my_tool"

        tool = FakeTool(MagicMock())
        at = AvailableTools([tool])
        assert at.contains_tool_class(FakeTool)

    def test_tool_names_sorted(self):
        tools = []
        for name in ["z_tool", "a_tool", "m_tool"]:
            t = MagicMock(spec=Tool)
            t.get_name_from_cls.return_value = name
            tools.append(t)

        at = AvailableTools(tools)
        assert at.tool_names == ["a_tool", "m_tool", "z_tool"]


# ── ToolManager ──────────────────────────────────────────────────────

class TestToolManager:
    def test_empty_after_init(self):
        from serena.tool_manager import ToolManager

        tm = ToolManager()
        assert tm.all_tools == {}
        assert len(tm.exposed_tools) == 0
        assert len(tm.active_tools) == 0

    @patch("serena.tools.ToolRegistry")
    def test_register_all_instantiates_tools(self, mock_registry_class):
        from serena.tool_manager import ToolManager

        mock_registry = mock_registry_class.return_value
        tool_cls_a = MagicMock(spec=type)
        tool_cls_a.return_value = MagicMock()
        tool_cls_b = MagicMock(spec=type)
        tool_cls_b.return_value = MagicMock()
        mock_registry.get_all_tool_classes.return_value = [tool_cls_a, tool_cls_b]

        tm = ToolManager()
        agent = MagicMock()
        names = tm.register_all(agent)

        assert len(tm.all_tools) == 2
        assert len(names) == 2

    def test_properties_return_expected_types(self):
        from serena.tool_manager import ToolManager

        tm = ToolManager()
        assert isinstance(tm.all_tools, dict)
        assert isinstance(tm.exposed_tools, AvailableTools)
        assert isinstance(tm.active_tools, AvailableTools)
        assert isinstance(tm.base_toolset, ToolSet)
