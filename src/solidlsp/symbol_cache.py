"""
Symbol cache classes extracted from SolidLanguageServer.

Provides ``RawSymbolCache`` and ``HighLevelSymbolCache`` for two-tier
(document symbols) caching with both monolithic and per-file storage modes.
"""

import hashlib
import logging
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any, Optional

from solidlsp.util.cache import load_cache, save_cache
from solidlsp.util.per_file_cache import load_cache_entry, migrate_monolithic_to_per_file, save_cache_entry

log = logging.getLogger(__name__)


def _derive_ls_specific_version_from_source(cls: type) -> Hashable:
    """
    Derive an LS-specific cache version from the subclass source file mtime.

    This is used as a fallback auto-versioning mechanism: when the subclass
    source file changes (e.g. ``_normalize_symbol_name`` is modified), the
    cache version changes, invalidating stale caches.
    """
    import inspect
    import os

    try:
        source_file = inspect.getfile(cls)
        mtime = os.path.getmtime(source_file)
        return int(mtime)
    except (OSError, TypeError):
        return 1


# ── Raw Symbol Cache ────────────────────────────────────────────────────


class RawSymbolCache:
    """
    Cache for raw document symbols (``list[DocumentSymbol]`` or ``list[SymbolInformation]``).

    Manages an in-memory dict ``{relative_path: (content_hash, raw_symbols)}``
    with optional per-file persistence for lazy loading and granular saves.
    """

    RAW_DOCUMENT_SYMBOLS_CACHE_VERSION = 1
    """Global version identifier; bump when the raw cache storage format changes."""
    RAW_DOCUMENT_SYMBOL_CACHE_FILENAME = "raw_document_symbols.pkl"
    RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK = "document_symbols_cache_v23-06-25.pkl"

    def __init__(
        self,
        cache_dir: Path,
        cache_storage_mode: str,
        version_func: Callable[[], tuple[Hashable, ...]],
    ) -> None:
        """
        :param cache_dir: The per-language cache directory.
        :param cache_storage_mode: ``"monolithic"`` or ``"per_file"``.
        :param version_func: A callable returning the current cache version tuple.
            Called during save/load to ensure version consistency.
        """
        self.cache_dir = cache_dir
        self._cache_storage_mode = cache_storage_mode
        self._version_func = version_func

        self._cache: dict[str, tuple[str, Any]] = {}
        """Maps relative file paths to (file_content_hash, raw_root_symbols)."""
        self._is_modified: bool = False

        self._load()

    # -- public interface --------------------------------------------------

    @property
    def cache(self) -> dict[str, tuple[str, Any]]:
        """Direct access to the backing dict (for testing / legacy compat)."""
        return self._cache

    @property
    def is_modified(self) -> bool:
        """Whether the in-memory cache has unsaved changes (monolithic mode)."""
        return self._is_modified

    def get(self, key: str, content_hash: str) -> Any | None:
        """
        Return cached raw symbols for *key* if the content hash matches.

        :returns: The cached value, or *None* on miss / staleness.
        """
        # In per-file mode, lazily load entry from disk if not in memory
        if self._cache_storage_mode == "per_file" and key not in self._cache:
            entry = self._load_per_file_entry(key)
            if entry is not None:
                self._cache[key] = entry

        entry = self._cache.get(key)
        if entry is None:
            return None

        cached_hash, data = entry
        if cached_hash == content_hash:
            return data
        return None

    def set(self, key: str, content_hash: str, data: Any) -> None:
        """Store *data* in the cache under *key* with the given *content_hash*."""
        self._cache[key] = (content_hash, data)
        if self._cache_storage_mode == "per_file":
            self._save_per_file_entry(key, (content_hash, data))
        else:
            self._is_modified = True

    def invalidate(self, key: str) -> None:
        """Remove the cache entry for *key* (if any)."""
        self._cache.pop(key, None)

    def save(self) -> None:
        """
        Persist the in-memory cache to disk (monolithic mode only).

        In per-file mode entries are written immediately via ``set()``,
        so this is a no-op.
        """
        if self._cache_storage_mode == "per_file":
            return
        if not self._is_modified:
            return

        cache_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME
        log.info("Saving raw document symbols cache to %s", cache_file)
        try:
            save_cache(str(cache_file), self._version(), self._cache)
            self._is_modified = False
        except Exception as e:
            log.error("Failed to save raw document symbols cache: %s", e)

    # -- loading -----------------------------------------------------------

    def _version(self) -> tuple[Hashable, ...]:
        return self._version_func()

    def _load(self) -> None:
        """Load or migrate the cache from disk."""
        if self._cache_storage_mode == "per_file":
            self._migrate_monolithic_cache()
            return

        cache_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME

        if not cache_file.exists():
            self._try_load_legacy()
            return

        try:
            saved = load_cache(str(cache_file), self._version())
            if saved is not None:
                self._cache = saved
                log.info("Loaded %d entries from raw document symbols cache.", len(self._cache))
        except Exception as e:
            log.warning("Failed to load raw document symbols cache: %s; ignoring.", e)

    def _try_load_legacy(self) -> None:
        """Migrate from the legacy (v23-06-25) monolithic cache format."""
        legacy_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK
        if not legacy_file.exists():
            return

        from serena.util.pickle_utils import load_pickle

        try:
            legacy_cache: dict[str, tuple[str, tuple[list, list]]] = load_pickle(legacy_file)
            log.info("Migrating legacy document symbols cache with %d entries", len(legacy_cache))
            migrated: dict[str, tuple[str, Any]] = {}
            for cache_key, (file_hash, (all_symbols, root_symbols)) in legacy_cache.items():
                if cache_key.endswith("-True"):  # include_body=True
                    new_key = cache_key[:-5]
                    migrated[new_key] = (file_hash, root_symbols)
            if migrated:
                self._cache = migrated
                self._is_modified = True
                self.save()
            legacy_file.unlink(missing_ok=True)
        except Exception as e:
            log.error("Legacy cache migration failed: %s", e)

    def _migrate_monolithic_cache(self) -> None:
        """Migrate a monolithic raw cache file to per-file entries."""
        raw_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME
        if not raw_file.exists():
            return

        try:
            from solidlsp.util.per_file_cache import migrate_monolithic_to_per_file

            raw_loaded, high_level_loaded = migrate_monolithic_to_per_file(
                self.cache_dir,
                "document_symbols.pkl",  # high-level filename (may not exist)
                self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME,
                self._version(),
                self._version(),
            )
            self._cache = raw_loaded
        except Exception as e:
            log.warning("Failed to migrate monolithic raw cache: %s", e)

    # -- per-file helpers --------------------------------------------------

    def _load_per_file_entry(self, relative_path: str) -> Optional[tuple[str, Any]]:
        return load_cache_entry(self.cache_dir, relative_path, self._version())

    def _save_per_file_entry(self, relative_path: str, entry: tuple[str, Any]) -> None:
        save_cache_entry(self.cache_dir, relative_path, self._version(), entry)


# ── High-level Symbol Cache ─────────────────────────────────────────────


class HighLevelSymbolCache:
    """
    Cache for processed (high-level) ``DocumentSymbols`` objects.

    Same storage pattern as ``RawSymbolCache`` but for
    ``{relative_path: (content_hash, DocumentSymbols)}``.

    Optionally accepts a *fingerprint_func* that captures language
    server-specific configuration (build flags, env vars, etc.).  When the
    fingerprint changes the cache is invalidated.
    """

    DOCUMENT_SYMBOL_CACHE_VERSION = 4
    DOCUMENT_SYMBOL_CACHE_FILENAME = "document_symbols.pkl"

    def __init__(
        self,
        cache_dir: Path,
        cache_storage_mode: str,
        version_func: Callable[[], tuple[Hashable, ...]],
    ) -> None:
        """
        :param cache_dir: The per-language cache directory.
        :param cache_storage_mode: ``"monolithic"`` or ``"per_file"``.
        :param version_func: A callable returning the current cache version tuple.
        """
        self.cache_dir = cache_dir
        self._cache_storage_mode = cache_storage_mode
        self._version_func = version_func

        self._cache: dict[str, tuple[str, Any]] = {}
        """Maps relative file paths to (file_content_hash, DocumentSymbols)."""
        self._is_modified: bool = False

        self._load()

    # -- public interface --------------------------------------------------

    @property
    def cache(self) -> dict[str, tuple[str, Any]]:
        return self._cache

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    def get(self, key: str, content_hash: str) -> Any | None:
        """Return cached ``DocumentSymbols`` for *key* if the content hash matches."""
        if self._cache_storage_mode == "per_file" and key not in self._cache:
            entry = self._load_per_file_entry(key)
            if entry is not None:
                self._cache[key] = entry

        entry = self._cache.get(key)
        if entry is None:
            return None

        cached_hash, data = entry
        if cached_hash == content_hash:
            return data
        return None

    def set(self, key: str, content_hash: str, data: Any) -> None:
        """Store *data* in the cache under *key*."""
        self._cache[key] = (content_hash, data)
        if self._cache_storage_mode == "per_file":
            self._save_per_file_entry(key, (content_hash, data))
        else:
            self._is_modified = True

    def invalidate(self, key: str) -> None:
        """Remove the cache entry for *key*."""
        self._cache.pop(key, None)

    def save(self) -> None:
        """Persist in-memory cache to disk (monolithic mode only)."""
        if self._cache_storage_mode == "per_file":
            return
        if not self._is_modified:
            return

        cache_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME
        log.info("Saving document symbols cache to %s", cache_file)
        try:
            save_cache(str(cache_file), self._version(), self._cache)
            self._is_modified = False
        except Exception as e:
            log.error("Failed to save document symbols cache: %s", e)

    # -- loading -----------------------------------------------------------

    def _version(self) -> tuple[Hashable, ...]:
        return self._version_func()

    def _load(self) -> None:
        """Load or migrate the cache from disk."""
        if self._cache_storage_mode == "per_file":
            self._try_migrate_high_level()
            return

        cache_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME
        if not cache_file.exists():
            return

        try:
            saved = load_cache(str(cache_file), self._version())
            if saved is not None:
                self._cache = saved
                log.info("Loaded %d entries from document symbols cache.", len(self._cache))
        except Exception as e:
            log.warning("Failed to load document symbols cache: %s; ignoring.", e)

    def _try_migrate_high_level(self) -> None:
        """Migrate a monolithic high-level cache to per-file entries."""
        high_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME
        if not high_file.exists():
            return

        try:
            from solidlsp.util.per_file_cache import migrate_monolithic_to_per_file

            _, high_loaded = migrate_monolithic_to_per_file(
                self.cache_dir,
                self.DOCUMENT_SYMBOL_CACHE_FILENAME,
                "raw_document_symbols.pkl",  # raw filename (may not exist)
                self._version(),
                self._version(),
            )
            self._cache = high_loaded
        except Exception as e:
            log.warning("Failed to migrate high-level monolithic cache: %s", e)

    # -- per-file helpers --------------------------------------------------

    def _load_per_file_entry(self, relative_path: str) -> Optional[tuple[str, Any]]:
        return load_cache_entry(self.cache_dir, relative_path, self._version())

    def _save_per_file_entry(self, relative_path: str, entry: tuple[str, Any]) -> None:
        save_cache_entry(self.cache_dir, relative_path, self._version(), entry)


# ── Cache version helpers ────────────────────────────────────────────────


def make_raw_cache_version(
    ls_specific_version: Hashable = 1,
    *,
    base_class: type = RawSymbolCache,
) -> Callable[[], tuple[Hashable, ...]]:
    """
    Build a version function for ``RawSymbolCache``.

    The returned callable returns ``(RAW_DOCUMENT_SYMBOLS_CACHE_VERSION, ls_specific_version)``.
    """
    base = base_class.RAW_DOCUMENT_SYMBOLS_CACHE_VERSION

    def version_func() -> tuple[Hashable, ...]:
        return (base, ls_specific_version)

    return version_func


def make_high_level_cache_version(
    fingerprint_func: Callable[[], Hashable | None] | None = None,
    *,
    base_class: type = HighLevelSymbolCache,
) -> Callable[[], tuple[Hashable, ...]]:
    """
    Build a version function for ``HighLevelSymbolCache``.

    If *fingerprint_func* is provided, the version tuple includes the
    fingerprint value (which enables configuration-based cache invalidation).
    """
    base = base_class.DOCUMENT_SYMBOL_CACHE_VERSION

    def version_func() -> tuple[Hashable, ...]:
        if fingerprint_func is not None:
            fp = fingerprint_func()
            if fp is not None:
                return (base, fp)
        return (base,)

    return version_func
