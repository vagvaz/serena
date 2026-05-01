# src/solidlsp/util/

## Responsibility
Utility modules supporting the LSP framework: symbol cache persistence (both monolithic and per-file), Metals H2 database lock management, cross-platform subprocess helpers, and safe ZIP extraction.

## Key Files
- `cache.py` — `load_cache` / `save_cache`: simple version-verified monolithic pickle cache used by `SolidLanguageServer` for document symbol caches.
- `metals_db_utils.py` — Scala Metals H2 database lock detection: parses `.lock.db` files to distinguish active instances from stale locks, with `check_metals_db_status()` and `cleanup_stale_lock()` for safe multi-instance coordination.
- `per_file_cache.py` — Per-file cache storage (alternative to monolithic): each cache entry is an individual pickle file sharded by MD5 hash prefix. Enables lazy loading, granular saves, and better branch-switch persistence. Includes `migrate_monolithic_to_per_file()` for automatic migration.
- `subprocess_util.py` — `subprocess_kwargs()` (adds `CREATE_NO_WINDOW` on Windows) and `quote_arg()` (shell-safe argument quoting via `shlex.quote` on POSIX, double-quoting on Windows).
- `zip.py` — `SafeZipExtractor`: robust ZIP extraction with include/exclude glob patterns, long-path support on Windows, and per-file error tolerance (skips failing entries instead of aborting).

## Design Patterns
- **Pluggable Cache Strategy**: `cache.py` and `per_file_cache.py` expose identical APIs (`load_cache`/`save_cache` vs. `load_cache_entry`/`save_cache_entry`), selected by `SolidLSPSettings.cache_storage_mode` — Strategy pattern.
- **Atomic Writes**: Per-file cache uses temp-file + rename for crash-safe persistence.
- **Defensive State Detection**: `metals_db_utils.py` parses H2 lock files via regex, cross-references PIDs/ports with `psutil`, and defaults to "stale" on ambiguity to prevent data corruption.
- **Fail-Open Extraction**: `SafeZipExtractor` logs and skips individual archive members that fail, rather than failing the entire extraction.

## Flow
- **Cache read**: `SolidLanguageServer` calls `load_cache()` (monolithic) or `load_cache_entry()` (per-file) on startup to hydrate in-memory caches; version mismatch returns `None` to force a rebuild.
- **Cache write**: After LS returns document symbols, entries are saved back via the selected strategy. In per-file mode, only changed entries are rewritten.
- **ZIP extraction**: `SafeZipExtractor.extract_all()` iterates archive members, applies filter patterns, and writes each with directory creation and Windows long-path handling.

## Integration
- Consumed by: `solidlsp.ls.py` (caching via `cache.py`/`per_file_cache.py`), `solidlsp.ls_process.py` (subprocess via `subprocess_util.py`), language server modules (ZIP extraction for dependency downloads)
- Depends on: `serena.util.pickle_utils` (pickle I/O), `psutil` (process/network inspection in metals_db_utils), standard library (`hashlib`, `zipfile`, `tempfile`, `shlex`)
