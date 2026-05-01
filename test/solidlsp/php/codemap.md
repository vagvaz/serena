# test/solidlsp/php/

## Responsibility
Tests for PHP language servers — PHPactor (`Language.PHP_PHPACTOR`) and/or Intelephense.

## Test Approach
Uses `test_php_basic.py` with parametrized `language_server` fixture. Validates symbol resolution, references, and server communication for PHP source files.

## Markers
`@pytest.mark.php`
