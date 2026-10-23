from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ascender.main.models import WorkflowJobTemplate, User, Team


@pytest.mark.django_db
@pytest.mark.parametrize('state', ('present', 'absent'))
def test_grant_organization_permission(run_module, admin_user, organization, state):
    rando = User.objects.create(username='rando')
    if state == 'absent':
        organization.admin_role.members.add(rando)

    result = run_module('role', {'users': [rando.username], 'organizations': [organization.name], 'role': 'admin', 'state': state}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    if state == 'present':
        assert rando in organization.execute_role
    else:
        assert rando not in organization.execute_role


@pytest.mark.django_db
@pytest.mark.parametrize('state', ('present', 'absent'))
def test_grant_workflow_permission(run_module, admin_user, organization, state):
    wfjt = WorkflowJobTemplate.objects.create(organization=organization, name='foo-workflow')
    rando = User.objects.create(username='rando')
    if state == 'absent':
        wfjt.execute_role.members.add(rando)

    result = run_module('role', {'users': [rando.username], 'workflows': [wfjt.name], 'role': 'execute', 'state': state}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    if state == 'present':
        assert rando in wfjt.execute_role
    else:
        assert rando not in wfjt.execute_role


@pytest.mark.django_db
@pytest.mark.parametrize('state', ('present', 'absent'))
def test_grant_workflow_list_permission(run_module, admin_user, organization, state):
    wfjt = WorkflowJobTemplate.objects.create(organization=organization, name='foo-workflow')
    rando = User.objects.create(username='rando')
    if state == 'absent':
        wfjt.execute_role.members.add(rando)

    result = run_module(
        'role',
        {'users': [rando.username], 'lookup_organization': wfjt.organization.name, 'workflows': [wfjt.name], 'role': 'execute', 'state': state},
        admin_user,
    )
    assert not result.get('failed', False), result.get('msg', result)

    if state == 'present':
        assert rando in wfjt.execute_role
    else:
        assert rando not in wfjt.execute_role


@pytest.mark.django_db
@pytest.mark.parametrize('state', ('present', 'absent'))
def test_grant_workflow_approval_permission(run_module, admin_user, organization, state):
    wfjt = WorkflowJobTemplate.objects.create(organization=organization, name='foo-workflow')
    rando = User.objects.create(username='rando')
    if state == 'absent':
        wfjt.execute_role.members.add(rando)

    result = run_module('role', {'users': [rando.username], 'workflows': [wfjt.name], 'role': 'approval', 'state': state}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    if state == 'present':
        assert rando in wfjt.approval_role
    else:
        assert rando not in wfjt.approval_role


@pytest.mark.django_db
def test_invalid_role(run_module, admin_user, project):
    rando = User.objects.create(username='rando')
    result = run_module('role', {'users': [rando.username], 'projects': [project.name], 'role': 'adhoc', 'state': 'present'}, admin_user)
    assert result.get('failed', False)
    msg = result.get('msg')
    assert 'has no role adhoc_role' in msg
    assert 'available roles: admin_role, use_role, update_role, read_role' in msg


@pytest.mark.django_db
@pytest.mark.parametrize('grantees', ({}, {'users': []}, {'teams': []}, {'users': [], 'teams': []}))
def test_no_grantee_fails(run_module, admin_user, organization, grantees):
    """A role with no user or team grants nothing, so it fails rather than reporting ok."""
    params = dict(grantees, organizations=[organization.name], role='admin', state='present')
    result = run_module('role', params, admin_user)
    assert result.get('failed', False), result
    assert 'one of users or teams is required' in result['msg']


@pytest.mark.django_db
def test_teams_only_with_empty_users_grants(run_module, admin_user, organization, project):
    """The roles role sends users: [] beside teams when enforcing defaults; the team still gets the role."""
    team = Team.objects.create(name='foo-team', organization=organization)
    result = run_module('role', {'users': [], 'teams': [team.name], 'projects': [project.name], 'role': 'admin', 'state': 'present'}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert team.member_role in project.admin_role.parents.all()


@pytest.mark.django_db
@pytest.mark.parametrize('resources', ({}, {'credentials': []}, {k: [] for k in (
    'credentials', 'inventories', 'instance_groups', 'job_templates', 'organizations', 'projects', 'target_teams', 'workflows')}))
def test_no_resource_fails(run_module, admin_user, resources):
    """A role with a grantee but no resource grants nothing, so it fails rather than reporting ok; [] is what the roles role sends."""
    rando = User.objects.create(username='rando')
    result = run_module('role', dict(resources, users=[rando.username], role='use', state='present'), admin_user)
    assert result.get('failed', False), result
    assert 'one of credentials, inventories, instance_groups, job_templates, organizations, projects, target_teams, workflows is required' in result['msg']
