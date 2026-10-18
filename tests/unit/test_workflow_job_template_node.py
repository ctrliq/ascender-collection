# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ascender.main.models import WorkflowJobTemplateNode, WorkflowJobTemplate, JobTemplate, UnifiedJobTemplate


@pytest.fixture
def job_template(project, inventory):
    return JobTemplate.objects.create(
        project=project,
        inventory=inventory,
        playbook='helloworld.yml',
        name='foo-jt',
        ask_variables_on_launch=True,
        ask_credential_on_launch=True,
        ask_limit_on_launch=True,
    )


@pytest.fixture
def wfjt(organization):
    WorkflowJobTemplate.objects.create(organization=None, name='foo-workflow')  # to test org scoping
    return WorkflowJobTemplate.objects.create(organization=organization, name='foo-workflow')


@pytest.mark.django_db
def test_create_workflow_job_template_node(run_module, admin_user, wfjt, job_template):
    this_identifier = '42🐉'
    result = run_module(
        'workflow_job_template_node',
        {
            'identifier': this_identifier,
            'workflow_job_template': 'foo-workflow',
            'organization': wfjt.organization.name,
            'unified_job_template': 'foo-jt',
            'state': 'present',
        },
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)

    node = WorkflowJobTemplateNode.objects.get(identifier=this_identifier)

    result.pop('invocation', None)
    assert result == {"name": this_identifier, "id": node.id, "changed": True}  # FIXME: should this be identifier instead

    assert node.identifier == this_identifier
    assert node.workflow_job_template_id == wfjt.id
    assert node.unified_job_template_id == job_template.id


@pytest.mark.django_db
def test_create_workflow_job_template_node_approval_node(run_module, admin_user, wfjt, job_template):
    """This is a part of the API contract for creating approval nodes"""
    this_identifier = '42🐉'
    result = run_module(
        'workflow_job_template_node',
        {
            'identifier': this_identifier,
            'workflow_job_template': wfjt.name,
            'organization': wfjt.organization.name,
            'approval_node': {'name': 'foo-jt-approval'},
        },
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed', False), result

    node = WorkflowJobTemplateNode.objects.get(identifier=this_identifier)
    approval_node = UnifiedJobTemplate.objects.get(name='foo-jt-approval')

    assert result['id'] == approval_node.id

    assert node.identifier == this_identifier
    assert node.workflow_job_template_id == wfjt.id
    assert node.unified_job_template_id is approval_node.id


@pytest.mark.django_db
def test_make_use_of_prompts(run_module, admin_user, wfjt, job_template, machine_credential, vault_credential):
    result = run_module(
        'workflow_job_template_node',
        {
            'identifier': '42',
            'workflow_job_template': 'foo-workflow',
            'organization': wfjt.organization.name,
            'unified_job_template': 'foo-jt',
            'extra_data': {'foo': 'bar', 'another-foo': {'barz': 'bar2'}},
            'limit': 'foo_hosts',
            'credentials': [machine_credential.name, vault_credential.name],
            'state': 'present',
        },
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed', False)

    node = WorkflowJobTemplateNode.objects.get(identifier='42')

    assert node.limit == 'foo_hosts'
    assert node.extra_data == {'foo': 'bar', 'another-foo': {'barz': 'bar2'}}
    assert set(node.credentials.all()) == set([machine_credential, vault_credential])


@pytest.mark.django_db
def test_create_with_edges(run_module, admin_user, wfjt, job_template):
    next_nodes = [
        WorkflowJobTemplateNode.objects.create(identifier='foo{0}'.format(i), workflow_job_template=wfjt, unified_job_template=job_template) for i in range(3)
    ]

    result = run_module(
        'workflow_job_template_node',
        {
            'identifier': '42',
            'workflow_job_template': 'foo-workflow',
            'organization': wfjt.organization.name,
            'unified_job_template': 'foo-jt',
            'success_nodes': ['foo0'],
            'always_nodes': ['foo1'],
            'failure_nodes': ['foo2'],
            'state': 'present',
        },
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed', False)

    node = WorkflowJobTemplateNode.objects.get(identifier='42')

    assert list(node.success_nodes.all()) == [next_nodes[0]]
    assert list(node.always_nodes.all()) == [next_nodes[1]]
    assert list(node.failure_nodes.all()) == [next_nodes[2]]


def link_node(run_module, admin_user, wfjt, **edges):
    params = {
        'identifier': 'a',
        'workflow_job_template': wfjt.name,
        'organization': wfjt.organization.name,
        'success_nodes': [],
        'always_nodes': [],
        'failure_nodes': [],
    }
    params.update(edges)
    result = run_module('workflow_job_template_node', params, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    return result


@pytest.fixture
def chain(wfjt, job_template):
    return {
        identifier: WorkflowJobTemplateNode.objects.create(identifier=identifier, workflow_job_template=wfjt, unified_job_template=job_template)
        for identifier in 'abc'
    }


def edges_of(node):
    return {
        'success': sorted(n.identifier for n in node.success_nodes.all()),
        'always': sorted(n.identifier for n in node.always_nodes.all()),
        'failure': sorted(n.identifier for n in node.failure_nodes.all()),
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    'before, after',
    [
        # always_nodes is synced before success_nodes, so this one used to fail with "Relationship not allowed"
        ('success_nodes', 'always_nodes'),
        ('failure_nodes', 'success_nodes'),
        ('failure_nodes', 'always_nodes'),
        ('always_nodes', 'failure_nodes'),
    ],
)
def test_edge_moves_to_another_type(run_module, admin_user, wfjt, chain, before, after):
    link_node(run_module, admin_user, wfjt, **{before: ['b']})

    result = link_node(run_module, admin_user, wfjt, **{after: ['b']})
    assert result.get('changed', False), result

    edges = edges_of(chain['a'])
    assert edges[after.split('_')[0]] == ['b']
    assert sum(len(targets) for targets in edges.values()) == 1


@pytest.mark.django_db
def test_edges_emptied_are_removed(run_module, admin_user, wfjt, chain):
    link_node(run_module, admin_user, wfjt, success_nodes=['b'], failure_nodes=['c'])

    result = link_node(run_module, admin_user, wfjt)
    assert result.get('changed', False), result

    assert edges_of(chain['a']) == {'success': [], 'always': [], 'failure': []}


@pytest.mark.django_db
def test_edges_not_given_are_left_alone(run_module, admin_user, wfjt, chain):
    chain['a'].success_nodes.add(chain['b'])

    result = run_module(
        'workflow_job_template_node',
        {'identifier': 'a', 'workflow_job_template': wfjt.name, 'organization': wfjt.organization.name, 'always_nodes': ['c']},
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)

    assert edges_of(chain['a']) == {'success': ['b'], 'always': ['c'], 'failure': []}


@pytest.mark.django_db
def test_unchanged_edges_report_no_change(run_module, admin_user, wfjt, chain):
    link_node(run_module, admin_user, wfjt, success_nodes=['b'], always_nodes=['c'])

    result = link_node(run_module, admin_user, wfjt, success_nodes=['b'], always_nodes=['c'])
    assert not result.get('changed', True), result


@pytest.mark.django_db
def test_edge_moves_between_condition_and_plain(run_module, admin_user, wfjt, chain):
    condition = {'identifier': 'b', 'artifact_key': 'ok', 'expected_value': 'yes'}
    link_node(run_module, admin_user, wfjt, condition_nodes=[condition])

    link_node(run_module, admin_user, wfjt, success_nodes=['b'], condition_nodes=[])
    assert edges_of(chain['a'])['success'] == ['b']
    assert chain['a'].condition_links_from.count() == 0

    link_node(run_module, admin_user, wfjt, condition_nodes=[condition])
    assert edges_of(chain['a'])['success'] == []
    assert chain['a'].condition_links_from.get().to_node_id == chain['b'].id


@pytest.mark.django_db
def test_only_remove_links_adds_nothing(run_module, admin_user, wfjt, chain):
    link_node(run_module, admin_user, wfjt, success_nodes=['b'])

    result = link_node(run_module, admin_user, wfjt, always_nodes=['c'], only_remove_links=True)
    assert result.get('changed', False), result
    assert edges_of(chain['a']) == {'success': [], 'always': [], 'failure': []}

    link_node(run_module, admin_user, wfjt, always_nodes=['c'])
    assert edges_of(chain['a']) == {'success': [], 'always': ['c'], 'failure': []}
