# test/solidlsp/scala/

## Responsibility
Tests for the Scala (Metals) language server integration.

## Test Approach
Three test files: `test_scala_language_server.py` (document symbols, references, definitions — currently module-level skipped with `pytest.skip` due to compilation requirements), `test_scala_stale_lock_handling.py` (handling of stale `.lock` files from sbt/Metals), `test_metals_db_utils.py` (database utility helpers for Metals). Uses parametrized `language_server` fixture.

## Markers
`@pytest.mark.scala`, module-level skip applied (needs compiled project).
