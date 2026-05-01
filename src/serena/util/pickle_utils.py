"""
Pickle utilities — replacing sensai.util.pickle.

Provides dump_pickle, load_pickle, and getstate for serialization.
"""

from __future__ import annotations

import bz2
import pickle
from contextlib import contextmanager
from copy import copy
from pathlib import Path
from typing import Any, Iterable


def dump_pickle(
    obj: Any,
    pickle_path: str | Path,
    protocol: int = pickle.HIGHEST_PROTOCOL,
    use_bz2: bool | None = None,
) -> None:
    """
    Pickle *obj* to *pickle_path*, optionally with bzip2 compression.

    :param use_bz2: if None, infer from ``.bz2`` file extension
    """
    if isinstance(pickle_path, Path):
        pickle_path = str(pickle_path)
    if use_bz2 is None:
        use_bz2 = pickle_path.endswith(".bz2")

    if use_bz2:
        with bz2.BZ2File(pickle_path, "wb") as f:
            pickle.dump(obj, f, protocol=protocol)
    else:
        with open(pickle_path, "wb") as f:
            pickle.dump(obj, f, protocol=protocol)


def load_pickle(
    path: str | Path,
    use_bz2: bool | None = None,
) -> Any:
    """
    Load a pickled object from *path*, optionally with bzip2 decompression.

    :param use_bz2: if None, infer from ``.bz2`` file extension
    """
    if isinstance(path, Path):
        path = str(path)
    if use_bz2 is None:
        use_bz2 = path.endswith(".bz2")

    if use_bz2:
        with bz2.BZ2File(path, "rb") as f:
            return pickle.load(f)
    else:
        with open(path, "rb") as f:
            return pickle.load(f)


def getstate(
    cls: type,
    obj: Any,
    transient_properties: Iterable[str] | None = None,
    excluded_properties: Iterable[str] | None = None,
    override_properties: dict[str, Any] | None = None,
    excluded_default_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Helper for safe ``__getstate__`` implementations.

    Calls parent ``__getstate__`` if available, otherwise falls back to
    ``obj.__dict__``.  Returns a copy so the caller can safely modify it.
    """
    parent = super(cls, obj)
    if hasattr(parent, "__getstate__"):
        d = parent.__getstate__()
    else:
        d = obj.__dict__
    d = copy(d)

    if transient_properties:
        for p in transient_properties:
            d[p] = None
    if excluded_properties:
        for p in excluded_properties:
            d.pop(p, None)
    if override_properties:
        d.update(override_properties)
    if excluded_default_properties:
        for p, default_val in excluded_default_properties.items():
            if p in d and d[p] == default_val:
                d.pop(p, None)
    return d
