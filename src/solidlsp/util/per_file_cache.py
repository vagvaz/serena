"""
Per-file symbol cache with content-hash-based invalidation.

Instead of storing all cache entries in one monolithic pickle file,
each entry is stored as an individual file keyed by a hash of the relative path.
This enables:
- Lazy loading: only load cache entries for files actually accessed
- Granular saves: only write changed entries, not the entire cache
- Branch switching: entries for unchanged files persist across switches

The API mirrors the monolithic ``load_cache``/``save_cache`` functions from ``cache.py``
so that ``SolidLanguageServer`` can switch between modes transparently.
"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from sensai.util.pickle import dump_pickle, load_pickle

log = logging.getLogger(__name__)

# Number of characters from the hash to use for sharding directories
_SHARD_PREFIX_LEN = 2

# Subdirectory name inside the language cache dir for per-file entries
_PER_FILE_SUBDIR = "entries"


def _cache_key_to_filename(relative_path: str) -> str:
    """Convert a relative file path to a cache filename using MD5 hash."""
    return hashlib.md5(relative_path.encode("utf-8")).hexdigest()


def _entries_dir(cache_dir: Path) -> Path:
    """Return the subdirectory that holds per-file cache entries."""
    return cache_dir / _PER_FILE_SUBDIR


def _cache_entry_path(cache_dir: Path, relative_path: str) -> Path:
    """Get the full path for a cache entry file."""
    entries = _entries_dir(cache_dir)
    filename = _cache_key_to_filename(relative_path)
    shard_prefix = filename[:_SHARD_PREFIX_LEN]
    return entries / shard_prefix / f"{filename}.pkl"


def _ensure_entry_dir(cache_dir: Path, relative_path: str) -> Path:
    """Ensure the shard directory exists and return the cache entry path."""
    entry_path = _cache_entry_path(cache_dir, relative_path)
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    return entry_path


def load_cache_entry(cache_dir: Path, relative_path: str, version: Any) -> Optional[Any]:
    """
    Load a single cache entry for the given relative path.

    :param cache_dir: The base cache directory for the language
    :param relative_path: The relative file path used as the cache key
    :param version: The expected cache version tuple
    :return: The cached object if found and version matches, None otherwise
    """
    entry_path = _cache_entry_path(cache_dir, relative_path)
    if not entry_path.exists():
        return None

    try:
        data = load_pickle(str(entry_path))
    except Exception:
        log.debug("Failed to load cache entry for %s, ignoring", relative_path)
        return None

    if not isinstance(data, dict) or "__cache_version" not in data:
        log.debug("Cache entry for %s has invalid format, ignoring", relative_path)
        return None

    saved_version = data["__cache_version"]
    if saved_version != version:
        log.debug("Cache entry for %s is outdated (expected %s, got %s)", relative_path, version, saved_version)
        return None

    return data["obj"]


def save_cache_entry(cache_dir: Path, relative_path: str, version: Any, obj: Any) -> None:
    """
    Save a single cache entry for the given relative path.

    Uses atomic write (temp file + rename) to prevent corruption on crash.

    :param cache_dir: The base cache directory for the language
    :param relative_path: The relative file path used as the cache key
    :param version: The cache version tuple
    :param obj: The object to cache
    """
    entry_path = _ensure_entry_dir(cache_dir, relative_path)
    data = {"__cache_version": version, "__cache_key": relative_path, "obj": obj}

    # Atomic write: write to temp file in same directory, then rename
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(entry_path.parent), suffix=".tmp")
        os.close(fd)
        dump_pickle(data, tmp_path)
        os.replace(tmp_path, str(entry_path))
    except Exception as e:
        log.error("Failed to save cache entry for %s: %s", relative_path, e)
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def delete_cache_entry(cache_dir: Path, relative_path: str) -> None:
    """Delete a single cache entry if it exists."""
    entry_path = _cache_entry_path(cache_dir, relative_path)
    if entry_path.exists():
        try:
            entry_path.unlink()
        except OSError:
            log.debug("Failed to delete cache entry for %s", relative_path)


def migrate_monolithic_to_per_file(
    cache_dir: Path,
    monolithic_filename: str,
    raw_filename: str,
    version: Any,
    raw_version: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Migrate from old monolithic pickle files to per-file cache.

    Reads the old monolithic files, writes each entry as an individual per-file entry,
    then deletes the old files.

    :param cache_dir: The base cache directory
    :param monolithic_filename: Name of the old monolithic cache file (document_symbols.pkl)
    :param raw_filename: Name of the old raw cache file (raw_document_symbols.pkl)
    :param version: Version for the high-level cache
    :param raw_version: Version for the raw cache
    :return: (raw_cache_dict, high_level_cache_dict) loaded from old files
    """
    raw_cache: dict[str, Any] = {}
    high_level_cache: dict[str, Any] = {}

    # Migrate raw document symbols
    raw_file = cache_dir / raw_filename
    if raw_file.exists():
        try:
            old_data = load_pickle(str(raw_file))
            if isinstance(old_data, dict) and "__cache_version" in old_data:
                if old_data["__cache_version"] == raw_version:
                    old_entries = old_data.get("obj", {})
                    log.info("Migrating %d raw symbol entries from monolithic cache to per-file", len(old_entries))
                    for relative_path, entry in old_entries.items():
                        save_cache_entry(cache_dir, relative_path, raw_version, entry)
                    raw_cache = old_entries
            raw_file.unlink()
            log.info("Removed old monolithic raw cache file: %s", raw_file)
        except Exception as e:
            log.warning("Failed to migrate raw cache from %s: %s", raw_file, e)

    # Migrate high-level document symbols
    high_level_file = cache_dir / monolithic_filename
    if high_level_file.exists():
        try:
            old_data = load_pickle(str(high_level_file))
            if isinstance(old_data, dict) and "__cache_version" in old_data:
                if old_data["__cache_version"] == version:
                    old_entries = old_data.get("obj", {})
                    log.info("Migrating %d document symbol entries from monolithic cache to per-file", len(old_entries))
                    for relative_path, entry in old_entries.items():
                        save_cache_entry(cache_dir, relative_path, version, entry)
                    high_level_cache = old_entries
            high_level_file.unlink()
            log.info("Removed old monolithic cache file: %s", high_level_file)
        except Exception as e:
            log.warning("Failed to migrate high-level cache from %s: %s", high_level_file, e)

    return raw_cache, high_level_cache
