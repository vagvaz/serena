# src/serena/generated/

## Responsibility
Holds auto-generated modules produced by build-time code generation tools, providing type-safe prompt template access for the agent.

## Key Files
- `generated_prompt_factory.py` — Auto-generated from `interprompt.autogenerate_prompt_factory_module`. Defines `PromptFactory(PromptFactoryBase)` with typed methods for each prompt template: `create_onboarding_prompt`, `create_system_prompt`, `create_connection_prompt`, `create_cc_system_prompt_override`, and `create_info_jet_brains_debug_repl`. Each method delegates to `PromptFactoryBase._render_prompt()` with the correct template name and typed parameters.

## Design Patterns
- **Code generation** — The module is not hand-written; it is regenerated when prompt templates change, via the `interprompt` code generator
- **Typed facade** over `PromptFactoryBase` — each template gets a dedicated method with explicit parameter names and types, improving IDE support and error checking
- **Dual access** — each template has both a `get_*_template_string()` method (returns raw template) and a `create_*()` method (renders with arguments)

## Flow
- `PromptFactory.create_system_prompt(...)` → calls `_render_prompt("system_prompt", locals())` → loads Jinja2 template from the registered template paths → renders with provided variables → returns the rendered string

## Integration
- Consumed by: `serena.agent`, `serena.tools.workflow_tools`, `serena.tools.jetbrains_tools`
- Depends on: `interprompt.prompt_factory.PromptFactoryBase`
