# test/

## Responsibility
Root test package for the Serena project. Contains integration tests for the `serena` application layer, language server integration tests via `solidlsp`, and test fixture repositories in `resources/`.

## Key Files
- **`__init__.py`**: Empty package marker.
- **`conftest.py`**: Session-scoped fixtures (`resources_dir`, `repo_path`, `language_server`, `project`, `project_with_ls`), language server lifecycle helpers (`start_ls_context`, `start_default_ls_context`), and environment-aware test gating (`is_ci`, `language_tests_enabled`, `get_pytest_markers`).

## Design Patterns
- **Fixture parametrization**: Language-specific fixtures are parametrized via `pytest.mark.parametrize` with the `Language` enum, using indirect fixtures to create per-language server/project instances.
- **Environment gating**: `_determine_disabled_languages()` checks for available tooling (clangd, ccls, lean, clojure CLI, php) and CI detection; `language_tests_enabled()` filters out languages whose server binary is unavailable.
- **Pytest markers**: Each language has a dedicated marker (e.g., `@pytest.mark.python`, `@pytest.mark.rust`) defined centrally in `_LANGUAGE_PYTEST_MARKERS` in `conftest.py`.
- **Resource repos**: Test repositories live under `resources/repos/<language>/test_repo/`, one per supported language.
- **Context managers**: `start_ls_context` and `project_context` ensure proper server shutdown even on test failure.

## Flow
```
conftest.py (session fixtures)
  ├── repo_path fixture      → get_repo_path(language) → Path
  ├── language_server fixture → start_default_ls_context() → SolidLanguageServer
  ├── project fixture         → Project.load() + cleanup
  └── project_with_ls         → Project + LS manager
```

## Integration
- All test fixtures depend on `serena` and `solidlsp` packages.
- Tests interact with real language server binaries; they are automatically skipped when the corresponding binary is not installed.
- Resource repositories are organized by language under `test/resources/repos/`.
