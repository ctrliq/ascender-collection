from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from awx.main.models import Inventory


@pytest.mark.django_db
def test_inventory_create(run_module, admin_user, organization):
    # Create an insights credential

    result = run_module(
        'inventory',
        {
            'name': 'foo-inventory',
            'organization': organization.name,
            'variables': {'foo': 'bar', 'another-foo': {'barz': 'bar2'}},
            'state': 'present',
        },
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)

    inv = Inventory.objects.get(name='foo-inventory')
    assert inv.variables == '{"foo": "bar", "another-foo": {"barz": "bar2"}}'

    result.pop('module_args', None)
    result.pop('invocation', None)
    assert result == {"name": "foo-inventory", "id": inv.id, "changed": True}

    assert inv.organization_id == organization.id


@pytest.mark.django_db
def test_invalid_smart_inventory_create(run_module, admin_user, organization):
    result = run_module(
        'inventory',
        {'name': 'foo-inventory', 'organization': organization.name, 'kind': 'smart', 'host_filter': 'ansible', 'state': 'present'},
        admin_user,
    )
    assert result.get('failed', False), result

    assert 'Invalid query ansible' in result['msg']


@pytest.mark.django_db
def test_valid_smart_inventory_create(run_module, admin_user, organization):
    result = run_module(
        'inventory',
        {'name': 'foo-inventory', 'organization': organization.name, 'kind': 'smart', 'host_filter': 'name=my_host', 'state': 'present'},
        admin_user,
    )
    assert not result.get('failed', False), result

    inv = Inventory.objects.get(name='foo-inventory')
    assert inv.host_filter == 'name=my_host'
    assert inv.kind == 'smart'
    assert inv.organization_id == organization.id


@pytest.mark.django_db
def test_inventory_allow_deletes_while_in_use(run_module, admin_user, organization):
    result = run_module(
        'inventory',
        {'name': 'foo-inventory', 'organization': organization.name, 'allow_deletes_while_in_use': True, 'state': 'present'},
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed', False), result

    inv = Inventory.objects.get(name='foo-inventory')
    assert inv.allow_deletes_while_in_use is True

    result = run_module(
        'inventory',
        {'name': 'foo-inventory', 'organization': organization.name, 'allow_deletes_while_in_use': False, 'state': 'present'},
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed', False), result

    inv.refresh_from_db()
    assert inv.allow_deletes_while_in_use is False


@pytest.mark.django_db
def test_inventory_allow_deletes_while_in_use_left_alone_when_omitted(run_module, admin_user, organization):
    result = run_module(
        'inventory',
        {'name': 'foo-inventory', 'organization': organization.name, 'allow_deletes_while_in_use': True, 'state': 'present'},
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)

    result = run_module(
        'inventory',
        {'name': 'foo-inventory', 'organization': organization.name, 'description': 'changed', 'state': 'present'},
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)

    inv = Inventory.objects.get(name='foo-inventory')
    assert inv.description == 'changed'
    assert inv.allow_deletes_while_in_use is True
