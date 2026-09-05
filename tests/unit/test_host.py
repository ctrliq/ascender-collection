from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from awx.main.models import Organization, Inventory, Host


@pytest.fixture
def inventory():
    org = Organization.objects.create(name='test-org')
    return Inventory.objects.create(name='test-inv', organization=org)


@pytest.mark.django_db
def test_create_host_with_instance_id(run_module, admin_user, inventory):
    result = run_module(
        'host',
        dict(name='test-host', inventory=inventory.name, instance_id='i-0abc123def456', state='present'),
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed'), result

    host = Host.objects.get(name='test-host')
    assert host.inventory == inventory
    assert host.instance_id == 'i-0abc123def456'


@pytest.mark.django_db
def test_host_instance_id_can_be_cleared(run_module, admin_user, inventory):
    Host.objects.create(inventory=inventory, name='test-host', instance_id='i-0abc123def456')

    result = run_module('host', dict(name='test-host', inventory=inventory.name, instance_id='', state='present'), admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed'), result

    assert Host.objects.get(name='test-host').instance_id == ''


@pytest.mark.django_db
def test_host_instance_id_left_alone_when_omitted(run_module, admin_user, inventory):
    Host.objects.create(inventory=inventory, name='test-host', instance_id='i-0abc123def456')

    result = run_module('host', dict(name='test-host', inventory=inventory.name, description='changed', state='present'), admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    host = Host.objects.get(name='test-host')
    assert host.description == 'changed'
    assert host.instance_id == 'i-0abc123def456'
