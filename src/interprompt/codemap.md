# src/interprompt/

## Responsibility
Provides a Jinja2-based prompt templating system with multi-language support, including YAML-driven prompt collection loading and auto-generation of typed prompt factory modules.

## Key Files
- `__init__.py` — Re-exports `autogenerate_prompt_factory_module` as the package's public API.
- `jinja_template.py` — Wraps a Jinja2 template string; parses undeclared variables as parameters and renders with kwarg expansion. Uses a `@singleton` `_JinjaEnvProvider` to share a single `jinja2.Environment`.
- `multilang_prompt.py` — Core module: defines `PromptTemplate`, `MultiLangPromptTemplate`, `PromptList`, `MultiLangPromptList`, and `MultiLangPromptCollection`. The collection loads prompts from YAML files (one directory or a priority-ordered list), supports language fallback modes (`ANY`, `EXCEPTION`, `USE_DEFAULT_LANG`), and enforces parameter consistency across languages.
- `prompt_factory.py` — Provides `PromptFactoryBase` (convenience wrapper around `MultiLangPromptCollection`) and `autogenerate_prompt_factory_module()`, which introspects a prompts directory and emits a `.py` file with a `PromptFactory` subclass containing one method per template/list.

## Design Patterns
- **Singleton** — `_JinjaEnvProvider` ensures a single shared `jinja2.Environment` instance.
- **Generic Container** — `_MultiLangContainer[T]` is a reusable generic that maps language codes to items; reused for both `PromptTemplate` and `PromptList`.
- **Code Generation** — `autogenerate_prompt_factory_module` reads YAML prompt definitions at build time and emits a Python module with typed convenience methods.
- **Fallback Strategy** — `LanguageFallbackMode` enum encapsulates three strategies for missing-language lookups.
- **Decorator** — `@singleton` in `util/class_decorators.py` wraps a class to ensure a single instance.

## Flow
1. YAML files (`.yml`/`.yaml`) in a `prompts_dir` are loaded by `MultiLangPromptCollection.__init__()`.
2. Each YAML entry is classified as a template string (→ `PromptTemplate` → `MultiLangPromptTemplate`) or a list (→ `PromptList` → `MultiLangPromptList`).
3. Prompt templates are rendered via `JinjaTemplate.render(**params)`, which delegates to the shared `jinja2.Environment`.
4. `PromptFactoryBase` wraps a `MultiLangPromptCollection` with a fixed language code for simpler single-language access.
5. `autogenerate_prompt_factory_module()` produces a concrete `PromptFactory` subclass whose methods call `_render_prompt()` / `_get_prompt_list()` by name.

## Integration
- Consumed by: Application code that needs typed, multilang prompt rendering (typically auto-generated `PromptFactory` subclasses).
- Depends on: `jinja2`, `pyyaml`, `serena.util.string_utils.ToStringMixin`, `interprompt.util.class_decorators.singleton`.
