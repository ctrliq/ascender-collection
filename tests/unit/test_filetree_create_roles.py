from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import re

import pytest
import yaml

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

try:
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 renders any string
    def trust_as_template(value):
        return value

ROLES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'roles')

OBJECT_ROLES = [
    {'Admin': {'resource_type': 'job_template', 'resource_names': ['JT1']}},
    {'Execute': {'resource_type': 'workflow_job_template', 'resource_names': ['WF1']}},
    {'Use': {'resource_type': 'inventory', 'resource_names': ['Inv1']}},
    {'Ad Hoc': {'resource_type': 'inventory', 'resource_names': ['Inv1']}},
    {'Member': {'resource_type': 'team', 'resource_names': ['T2']}},
    {'Approve': {'resource_type': 'organization', 'resource_names': ['Org1']}},
    {'Update': {'resource_type': 'project', 'resource_names': ['P1']}},
    {'Use': {'resource_type': 'credential', 'resource_names': ['C1']}},
    {'Admin': {'resource_type': 'instance_group', 'resource_names': ['IG1']}},
]


def roles_role_keys():
    """The entry keys the roles role passes to the role module."""
    with open(os.path.join(ROLES_DIR, 'roles', 'tasks', 'main.yml')) as f:
        text = f.read()
    return set(re.findall(r'__controller_role_item\.0\.(\w+)', text)) | {'role', 'roles'}


def role_module_choices():
    """The role names the role module accepts."""
    with open(os.path.join(ROLES_DIR, '..', 'plugins', 'modules', 'role.py')) as f:
        text = f.read()
    block = text[text.index('role=dict('):]
    return set(re.findall(r'"(\w+)"', block[:block.index(']')]))


def render(template, object_roles=None, **variables):
    path = os.path.join(ROLES_DIR, 'filetree_create', 'templates', template)
    with open(path) as f:
        source = f.read()
    templar = Templar(loader=DataLoader(), variables=dict(variables, object_roles=OBJECT_ROLES if object_roles is None else object_roles))
    return yaml.safe_load(templar.template(trust_as_template(source)))['controller_roles']


@pytest.mark.parametrize('template, variables, grantee', (
    ('current_user_roles.j2', {'username': 'jdoe'}, {'users': ['jdoe']}),
    ('current_team_roles.j2', {'team_name': 'T1'}, {'teams': ['T1']}),
))
def test_exported_roles_use_keys_the_roles_role_reads(template, variables, grantee):
    """Every exported entry names its grantee and resources with keys the roles role reads, so re-importing applies it."""
    entries = render(template, **variables)
    assert len(entries) == len(OBJECT_ROLES)
    readable = roles_role_keys()
    choices = role_module_choices()
    for entry in entries:
        assert set(entry) <= readable, entry
        assert {k: entry[k] for k in grantee} == grantee, entry
        assert entry['role'] in choices, entry


def match_task(kind):
    with open(os.path.join(ROLES_DIR, 'filetree_create', 'tasks', kind + '_roles.yml')) as f:
        tasks = yaml.safe_load(f)
    block = next(t for t in tasks if 'block' in t and t['name'].endswith('Map objects with roles (block)'))['block']
    return next(t for t in block if t['name'].endswith('Match objects with roles'))


def build_object_roles(kind, lookvar):
    """Loop the Match task over role name x resource type the way Ansible does, returning object_roles."""
    with open(os.path.join(ROLES_DIR, 'filetree_create', 'vars', 'main.yml')) as f:
        role_vars = yaml.safe_load(f)
    task = match_task(kind)
    facts = dict(role_vars, object_roles=[], **{kind + '_roles_lookvar': lookvar})
    names = sorted({r['name'] for r in lookvar})
    types = sorted({r['summary_fields']['resource_type'] for r in lookvar})
    for item in [(n, t) for n in names for t in types]:
        templar = Templar(loader=DataLoader(), variables=dict(facts, item=list(item)))
        # ansible-core before 2.19 renders a test result as the text 'True'/'False'
        conditions = task['when'] if isinstance(task['when'], list) else [task['when']]
        if all(templar.template(trust_as_template('{{ %s }}' % c)) in (True, 'True') for c in conditions):
            facts['object_roles'] = templar.template(trust_as_template(task['ansible.builtin.set_fact']['object_roles']))
    return facts['object_roles']


def api_role(name, resource_type, resource_name):
    return {'name': name, 'summary_fields': {'resource_type': resource_type, 'resource_name': resource_name}}


@pytest.mark.parametrize('kind', ('user', 'team'))
def test_roles_on_an_unknown_resource_type_are_not_exported(kind):
    """A role on a type the roles role can't name is left out of object_roles, so it never reaches the export."""
    object_roles = build_object_roles(kind, [api_role('Admin', 'job_template', 'JT1'), api_role('Admin', 'something_new', 'X1')])
    assert object_roles == [{'Admin': {'resource_names': ['JT1'], 'resource_type': 'job_template'}}]


@pytest.mark.parametrize('kind', ('user', 'team'))
def test_only_unknown_resource_types_export_nothing(kind):
    """With nothing exportable, object_roles is empty, so the export tasks (when: object_roles | length > 0) render nothing, not a null controller_roles."""
    assert build_object_roles(kind, [api_role('Admin', 'something_new', 'X1')]) == []


@pytest.mark.parametrize('kind, template, variables, grantee', (
    ('user', 'current_user_roles.j2', {'username': 'jdoe'}, {'users': ['jdoe']}),
    ('team', 'current_team_roles.j2', {'team_name': 'T1'}, {'teams': ['T1']}),
))
def test_every_known_resource_type_is_matched_and_exported(kind, template, variables, grantee):
    """The Match task keeps a role on every type the roles role can name, and the template exports each with readable keys."""
    lookvar = [api_role(name, value['resource_type'], value['resource_names'][0]) for entry in OBJECT_ROLES for name, value in entry.items()]
    object_roles = build_object_roles(kind, lookvar)
    known = {value['resource_type'] for entry in OBJECT_ROLES for value in entry.values()}
    assert {value['resource_type'] for entry in object_roles for value in entry.values()} == known
    entries = render(template, object_roles=object_roles, **variables)
    assert len(entries) == len(OBJECT_ROLES)
    readable = roles_role_keys()
    for entry in entries:
        assert set(entry) <= readable, entry
        assert {k: entry[k] for k in grantee} == grantee, entry
