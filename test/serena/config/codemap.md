# test/serena/config/

## Responsibility
Tests for Serena's configuration system, including `SerenaConfig`, `ProjectConfig`, global ignored paths, template path resolution, and config file loading robustness.

## Key Files
- **`__init__.py`**: Empty package marker.
- **`test_serena_config.py`**: Tests `ProjectConfig.autogenerate()` (language detection, gitignore support, disk persistence), `LanguageBackend` per-project override logic via `SerenaAgent`, `SerenaConfig.get_configured_project_serena_folder()` with `$projectDir`/`$projectFolderName` template placeholders, `MemoriesManager` with custom data folder paths, and config file robustness when project YAML is malformed.
- **`test_global_ignored_paths.py`**: Tests additive merge of global ignored paths (from `SerenaConfig`) with project-level ignored paths and `.gitignore` patterns, including glob patterns and three-way merge scenarios.

## Design Patterns
- **Class-based grouping**: Related test scenarios in separate classes (`TestProjectConfigAutogenerate`, `TestEffectiveLanguageBackend`, `TestGetConfiguredProjectSerenaFolder`, etc.).
- **Temp directory isolation**: Most tests create temporary directories with `tempfile.mkdtemp()` to avoid side effects.
- **Helper functions**: `_make_config_with_project()` and `_create_test_project()` reduce boilerplate across tests.

## Flow
```
test_serena_config.py
  ├── TestProjectConfigAutogenerate     → language detection, persistence, gitignore
  ├── TestProjectConfig                 → template completeness
  ├── TestProjectConfigLanguageBackend  → YAML round-trip for language_backend field
  ├── TestEffectiveLanguageBackend      → SerenaAgent backend resolution
  ├── TestGetConfiguredProjectSerenaFolder → template placeholder resolution
  ├── TestProjectSerenaDataFolder       → fallback logic in Project
  ├── TestSerenaConfigFromConfigFileRobustness → broken project.yml handling
  └── TestMemoriesManagerCustomPath     → custom data folder

test_global_ignored_paths.py
  ├── TestGlobalIgnoredPaths              → additive merge, globs, duplicates
  ├── TestRegisteredProjectGlobalIgnoredPaths → RegisteredProject plumbing
  ├── TestGlobalIgnoredPathsWithGitignore → three-way merge
  └── TestSerenaConfigIgnoredPaths        → config defaults and loading
```

## Integration
- Tests construct `Project` and `SerenaAgent` instances with controlled configurations.
- Some tests use real language server binaries to verify backend switching behavior.
