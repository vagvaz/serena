# test/serena/util/

## Responsibility
Tests for core utility modules in the `serena` package — gitignore parsing/scoping and headless environment detection.

## Key Files
- **`test_file_system.py`**: Comprehensive tests for `GitignoreParser` covering:
  - Multi-level `.gitignore` discovery (root, deep, nested)
  - Anchored vs. non-anchored pattern semantics
  - Negation patterns (`!pattern`)
  - Glob patterns (`**`, `*`, character classes)
  - Subdirectory scoping (patterns only apply within their subtree)
  - Comments, empty lines, escaped characters
  - `reload()` for dynamic `.gitignore` changes
  - Edge cases: empty/malformed files, `match_path` for root directory
  - 717 lines of test code across ~25 test methods.
- **`test_exception.py`**: Tests for `is_headless_environment()` and `show_fatal_exception_safe()` covering:
  - Headless detection: no `DISPLAY`, SSH sessions, WSL, Docker/CI containers
  - Platform-specific: Windows never reports headless
  - GUI fallback behavior: headless → skip GUI, headless+GUI works → show dialog, GUI fails → log warning
  - Always prints to stderr regardless of headless status

## Design Patterns
- **Temp directory with fixture structure**: `test_file_system.py` creates a realistic multi-directory repo structure with `.gitignore` files at multiple nesting levels.
- **Extensive parametrization**: Multiple test methods for each gitignore feature (anchored, non-anchored, double-star, negations, subdirectory scoping).
- **Environment mocking**: `test_exception.py` uses `unittest.mock.patch` for `sys.platform`, `os.environ`, `os.uname`, and `os.path.exists`.

## Flow
```
test_file_system.py
  ├── TestGitignoreParser → initialization, discovery, parsing, matching, reload
  └── (individual test methods for each pattern type)

test_exception.py
  ├── TestHeadlessEnvironmentDetection → platform/SSH/WSL/Docker detection
  └── TestShowFatalExceptionSafe → GUI fallback behavior
```

## Integration
- Tests import directly from `serena.util.file_system` and `serena.util.exception`.
- No external dependencies beyond Python stdlib, `pathspec`, and `pytest`.
