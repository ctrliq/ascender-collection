from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ascender.main.models import InstanceGroup, Instance


@pytest.mark.django_db
def test_instance_group_create(run_module, admin_user):
    result = run_module(
        'instance_group', {'name': 'foo-group', 'policy_instance_percentage': 34, 'policy_instance_minimum': 12, 'state': 'present'}, admin_user
    )
    assert not result.get('failed', False), result
    assert result['changed']

    ig = InstanceGroup.objects.get(name='foo-group')
    assert ig.policy_instance_percentage == 34
    assert ig.policy_instance_minimum == 12

    # Create a new instance in the DB
    new_instance = Instance.objects.create(hostname='foo.example.com')

    # Set the new instance group only to the one instnace
    result = run_module('instance_group', {'name': 'foo-group', 'instances': [new_instance.hostname], 'state': 'present'}, admin_user)
    assert not result.get('failed', False), result
    assert result['changed']

    ig = InstanceGroup.objects.get(name='foo-group')
    all_instance_names = []
    for instance in ig.instances.all():
        all_instance_names.append(instance.hostname)

    assert new_instance.hostname in all_instance_names, 'Failed to add instance to group'
    assert len(all_instance_names) == 1, 'Too many instances in group {0}'.format(','.join(all_instance_names))


@pytest.mark.django_db
def test_container_group_create(run_module, admin_user, kube_credential):
    pod_spec = "{ 'Nothing': True }"

    result = run_module('instance_group', {'name': 'foo-c-group', 'credential': kube_credential.id, 'is_container_group': True, 'state': 'present'}, admin_user)
    assert not result.get('failed', False), result['msg']
    assert result['changed']

    ig = InstanceGroup.objects.get(name='foo-c-group')
    assert ig.pod_spec_override == ''

    result = run_module(
        'instance_group',
        {'name': 'foo-c-group', 'credential': kube_credential.id, 'is_container_group': True, 'pod_spec_override': pod_spec, 'state': 'present'},
        admin_user,
    )
    assert not result.get('failed', False), result['msg']
    assert result['changed']

    ig = InstanceGroup.objects.get(name='foo-c-group')
    assert ig.pod_spec_override == pod_spec


@pytest.mark.django_db
def test_container_group_mesh_node(run_module, admin_user):
    """A container group behind a hop node is looked up by the node's hostname, and
    an empty string has to take it off again rather than be ignored.
    """
    hop = Instance.objects.create(hostname='hop.example.com', node_type='hop')

    result = run_module('instance_group', {'name': 'remote-c-group', 'is_container_group': True, 'mesh_node': hop.hostname}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result['changed']
    assert InstanceGroup.objects.get(name='remote-c-group').mesh_node_id == hop.id

    result = run_module('instance_group', {'name': 'remote-c-group', 'mesh_node': hop.hostname}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert not result['changed']

    result = run_module('instance_group', {'name': 'remote-c-group', 'mesh_node': ''}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result['changed']
    assert InstanceGroup.objects.get(name='remote-c-group').mesh_node is None


@pytest.mark.django_db
def test_container_group_mesh_node_must_be_hop(run_module, admin_user):
    execution = Instance.objects.create(hostname='exec.example.com', node_type='execution')

    result = run_module('instance_group', {'name': 'remote-c-group', 'is_container_group': True, 'mesh_node': execution.hostname}, admin_user)
    assert result.get('failed', False), result
    assert 'hop' in result['msg']
    assert not InstanceGroup.objects.filter(name='remote-c-group').exists()


@pytest.mark.django_db
def test_clearing_unset_fks_is_not_a_change(run_module, admin_user):
    """The role sends an empty credential and mesh_node to every group when it enforces
    defaults. On a group that has neither, that must compare equal to what the API
    returns, or check mode reports every instance group as changed on every run.
    """
    result = run_module('instance_group', {'name': 'plain-c-group', 'is_container_group': True}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    result = run_module('instance_group', {'name': 'plain-c-group', 'credential': '', 'mesh_node': '', '_ansible_check_mode': True}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert not result['changed']


@pytest.mark.django_db
def test_move_container_group_from_credential_to_mesh_node(run_module, admin_user, kube_credential):
    hop = Instance.objects.create(hostname='hop.example.com', node_type='hop')
    result = run_module('instance_group', {'name': 'move-c-group', 'is_container_group': True, 'credential': kube_credential.name}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    result = run_module('instance_group', {'name': 'move-c-group', 'credential': '', 'mesh_node': hop.hostname}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result['changed']
    ig = InstanceGroup.objects.get(name='move-c-group')
    assert ig.credential is None
    assert ig.mesh_node_id == hop.id
