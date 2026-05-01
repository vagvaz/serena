# test/solidlsp/terraform/

## Responsibility
Tests for the Terraform language server integration.

## Test Approach
Uses `test_terraform_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution for Terraform `.tf` files.

## Markers
`@pytest.mark.terraform`
