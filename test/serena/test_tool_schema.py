"""Tests for OpenAIToolSchemaAdapter — JSON Schema transformation for OpenAI compatibility."""

from serena.tool_schema import OpenAIToolSchemaAdapter


def test_integer_to_number():
    """'integer' type becomes 'number' with multipleOf: 1."""
    schema = {"type": "integer"}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["type"] == "number"
    assert result["multipleOf"] == 1


def test_integer_preserves_existing_multiple_of():
    """Existing multipleOf is preserved when converting integer to number."""
    schema = {"type": "integer", "multipleOf": 2}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["type"] == "number"
    assert result["multipleOf"] == 2


def test_string_type_unchanged():
    """Non-integer types are not modified."""
    schema = {"type": "string"}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["type"] == "string"


def test_removes_null_from_union():
    """'null' is removed from union type arrays."""
    schema = {"type": ["string", "null"]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["type"] == "string"


def test_integer_in_union_becomes_number():
    """'integer' in union type becomes 'number'."""
    schema = {"type": ["string", "integer"]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert "number" in result["type"]
    assert "integer" not in result["type"]


def test_null_only_union_falls_back_to_object():
    """Union containing only 'null' falls back to 'object'."""
    schema = {"type": ["null"]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["type"] == "object"


def test_integer_enum_becomes_number():
    """Enums of integers get type 'number' with multipleOf: 1."""
    schema = {"enum": [1, 2, 3]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["type"] == "number"
    assert result["multipleOf"] == 1


def test_string_enum_unchanged():
    """Enums of strings are not modified."""
    schema = {"enum": ["a", "b"]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert "type" not in result or result.get("type") != "number"


def test_simplifies_oneof_null():
    """oneOf with 'null' and another type simplifies to just that type."""
    schema = {"oneOf": [{"type": "string"}, {"type": "null"}]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert "oneOf" not in result
    assert result["type"] == "string"


def test_simplifies_anyof_null():
    """anyOf with 'null' and another type simplifies to just that type.
    Note: integer is not converted to number in this path."""
    schema = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert "anyOf" not in result
    assert result["type"] == "integer"  # not converted to number in this path


def test_collapses_identical_oneof():
    """oneOf entries both become 'number' after integer→number conversion.
    Not collapsed because one gets multipleOf: 1 and the other doesn't."""
    schema = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert "oneOf" in result
    assert all(e["type"] == "number" for e in result["oneOf"])


def test_recurses_into_properties():
    """Nested properties are recursively sanitized."""
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "name": {"type": "string"},
        },
    }
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["properties"]["count"]["type"] == "number"
    assert result["properties"]["count"]["multipleOf"] == 1
    assert result["properties"]["name"]["type"] == "string"


def test_recurses_into_items():
    """Array items are recursively sanitized."""
    schema = {
        "type": "array",
        "items": {"type": "integer"},
    }
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["items"]["type"] == "number"
    assert result["items"]["multipleOf"] == 1


def test_preserves_non_schema_fields():
    """Fields that aren't schema keywords are preserved."""
    schema = {"type": "string", "description": "A name", "default": "hello"}
    result = OpenAIToolSchemaAdapter.sanitize(schema)
    assert result["description"] == "A name"
    assert result["default"] == "hello"
