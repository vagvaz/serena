# test/solidlsp/ansible/

## Responsibility
Tests for the Ansible language server integration.

## Test Approach
Uses `test_ansible_basic.py` with parametrized `language_server` fixture. Validates basic symbol resolution and server communication for Ansible playbooks.

## Markers
`@pytest.mark.ansible`
