# src/interprompt/util/

## Responsibility
Provides lightweight utility decorators and helpers used by the `interprompt` package.

## Key Files
- `__init__.py` — Empty; makes the directory a package.
- `class_decorators.py` — Defines a `singleton` decorator that ensures a class is instantiated only once, returning the same instance on subsequent calls.

## Design Patterns
- **Decorator** — `singleton` is a closure-based decorator that stores the instance in a `nonlocal` variable and lazily creates it on first call.

## Flow
- Other modules import `singleton` and apply it to classes like `_JinjaEnvProvider` in `jinja_template.py`. The decorated function replaces the original class constructor, so every `_JinjaEnvProvider()` call returns the same object.

## Integration
- Consumed by: `interprompt.jinja_template` (via `from interprompt.util.class_decorators import singleton`).
- Depends on: Nothing outside `typing`.
