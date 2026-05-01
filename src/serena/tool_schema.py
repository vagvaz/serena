"""
JSON Schema transformation utilities for MCP tool schemas.

Provides OpenAIToolSchemaAdapter — extracting schema transformation logic
from mcp.py so that protocol concerns and schema adaptations are separated.
"""

from __future__ import annotations

from copy import deepcopy


class OpenAIToolSchemaAdapter:
    """
    Transforms MCP/JSON Schema tool schemas to be compatible with
    OpenAI's tool format.

    OpenAI tools don't support:
    - ``integer`` type (use ``number`` + ``multipleOf: 1`` instead)
    - ``null`` in union types
    - oneOf/anyOf schemas that collapse to a single effective type

    Usage::

        adapter = OpenAIToolSchemaAdapter()
        sanitized = adapter.sanitize(schema_dict)
    """

    @staticmethod
    def sanitize(schema: dict) -> dict:
        """
        Make a Pydantic/JSON Schema object compatible with OpenAI tool schema.

        - ``integer`` → ``number`` (``+ multipleOf: 1``)
        - Remove ``null`` from union type arrays
        - Coerce integer-only enums to number
        - Best-effort simplify ``oneOf``/``anyOf`` when they only differ
          by integer/number
        """
        s = deepcopy(schema)

        def walk(node):
            if not isinstance(node, dict):
                return node

            # ── handle type ──────────────────────────────────────────
            t = node.get("type")
            if isinstance(t, str):
                if t == "integer":
                    node["type"] = "number"
                    if "multipleOf" not in node:
                        node["multipleOf"] = 1
            elif isinstance(t, list):
                t2 = [x if x != "integer" else "number" for x in t if x != "null"]
                if not t2:
                    t2 = ["object"]
                node["type"] = t2[0] if len(t2) == 1 else t2
                if "integer" in t or "number" in t2:
                    node.setdefault("multipleOf", 1)

            # ── enums of integers → number ───────────────────────────
            if "enum" in node and isinstance(node["enum"], list):
                vals = node["enum"]
                if vals and all(isinstance(v, int) for v in vals):
                    node.setdefault("type", "number")
                    node.setdefault("multipleOf", 1)

            # ── simplify anyOf/oneOf when they differ only by type ───
            for key in ("oneOf", "anyOf"):
                if key in node and isinstance(node[key], list):
                    if len(node[key]) == 2:
                        types = [sub.get("type") for sub in node[key]]
                        if "null" in types:
                            non_null_type = next(t for t in types if t != "null")
                            if isinstance(non_null_type, str):
                                node["type"] = non_null_type
                                node.pop(key, None)
                                continue
                    simplified = []
                    changed = False
                    for sub in node[key]:
                        sub = walk(sub)
                        simplified.append(sub)
                    import json

                    canon = [json.dumps(x, sort_keys=True) for x in simplified]
                    if len(set(canon)) == 1:
                        only = simplified[0]
                        node.pop(key, None)
                        for k, v in only.items():
                            if k not in node:
                                node[k] = v
                        changed = True
                    if not changed:
                        node[key] = simplified

            # ── recurse into container schemas ────────────────────────
            for child_key in ("properties", "patternProperties", "definitions", "$defs"):
                if child_key in node and isinstance(node[child_key], dict):
                    for k, v in list(node[child_key].items()):
                        node[child_key][k] = walk(v)

            if "items" in node:
                node["items"] = walk(node["items"])

            for key in ("allOf",):
                if key in node and isinstance(node[key], list):
                    node[key] = [walk(x) for x in node[key]]

            if "if" in node:
                node["if"] = walk(node["if"])
            if "then" in node:
                node["then"] = walk(node["then"])
            if "else" in node:
                node["else"] = walk(node["else"])

            return node

        return walk(s)
