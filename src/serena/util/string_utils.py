"""
String utilities — replacing sensai.util.string.

Provides ToStringMixin, dict_string, and TextBuilder for consistent
string representation across Serena.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Optional

log = logging.getLogger(__name__)


# ── dict_string ──────────────────────────────────────────────────────

def dict_string(d: Mapping, brackets: str | None = None) -> str:
    """
    Convert a dict to a string of the form ``key=value, key=value, ...``,
    optionally enclosed by brackets.

    :param d: the dictionary
    :param brackets: e.g. ``"{}"`` to wrap in braces; None for no brackets
    """
    s = ", ".join(f"{k}={v}" for k, v in d.items())
    if brackets is not None:
        return brackets[:1] + s + brackets[-1:]
    return s


# ── TextBuilder ──────────────────────────────────────────────────────

class TextBuilder:
    """Accumulate lines of text and build a final string."""

    def __init__(self, initial_text: str | None = None) -> None:
        self._components: list[str] = []
        if initial_text is not None:
            self._components.append(initial_text)

    def build(self) -> str:
        return "\n".join(self._components)

    def with_lines(self, lines: Sequence[str], indent: int = 0) -> TextBuilder:
        for line in lines:
            line = line.rstrip()
            if indent > 0:
                line = " " * indent + line
            self._components.append(line)
        return self

    def with_lines_from_text(self, text: str, indent: int = 0) -> TextBuilder:
        return self.with_lines(text.splitlines(keepends=False), indent=indent)

    def with_line(self, line: str, indent: int = 0) -> TextBuilder:
        return self.with_lines([line], indent=indent)

    def with_line_conditional(self, cond: bool, line: str, indent: int = 0) -> TextBuilder:
        if cond:
            self.with_line(line, indent=indent)
        return self

    def with_text(self, text: str) -> TextBuilder:
        self._components.append(text)
        return self


# ── ToStringMixin ────────────────────────────────────────────────────

class ToStringMixin:
    """
    Provides ``__str__`` and ``__repr__`` based on the format
    ``ClassName[info]`` where *info* is derived from instance attributes.

    Override ``_tostring_includes()``, ``_tostring_excludes()``,
    ``_tostring_additional_entries()``, etc. to customise output.
    """

    @staticmethod
    def _tostring_class_name() -> str:
        return ""

    def _tostring_object_info(self) -> str | None:
        return None

    def _tostring_excludes(self) -> list[str]:
        return []

    def _tostring_includes(self) -> list[str]:
        return []

    def _tostring_includes_forced(self) -> list[str]:
        return []

    def _tostring_additional_entries(self) -> dict[str, Any]:
        return {}

    def _tostring_exclude_private(self) -> bool:
        return True

    def _tostring_exclude_exceptions(self) -> list[str]:
        return []

    def _collect_properties(self) -> dict[str, Any]:
        excludes = set(self._tostring_excludes())
        includes = self._tostring_includes()
        forced_includes = self._tostring_includes_forced()
        additional = self._tostring_additional_entries()

        if includes:
            props = {k: getattr(self, k) for k in includes if k not in excludes}
        else:
            props = {}
            for k, v in self.__dict__.items():
                if k in excludes:
                    continue
                if self._tostring_exclude_private() and k.startswith("_") and k not in self._tostring_exclude_exceptions():
                    continue
                display_name = k.lstrip("_") if k.startswith("_") else k
                props[display_name] = v

        for k, v in forced_includes:
            props[k] = v
        props.update(additional)
        return props

    def __str__(self) -> str:
        info = self._tostring_object_info()
        if info is None:
            props = self._collect_properties()
            info = ", ".join(f"{k}={v}" for k, v in props.items())
        cls_name = self._tostring_class_name() or type(self).__name__
        return f"{cls_name}[{info}]"

    def __repr__(self) -> str:
        info = self._tostring_object_info()
        if info is None:
            props = self._collect_properties()
            info = (
                f"id={id(self)}, "
                + ", ".join(f"{k}={v}" for k, v in props.items())
            )
        cls_name = self._tostring_class_name() or type(self).__name__
        return f"{cls_name}[{info}]"

    def pprint(self, file=sys.stdout) -> None:  # type: ignore[assignment]
        file.write(str(self) + "\n")
