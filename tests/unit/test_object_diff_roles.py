from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os

import pytest
import yaml

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

try:
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 renders any string
    def trust_as_template(value):
        return value

TASKS = os.path.join(os.path.dirname(__file__), '..', '..', 'roles', 'object_diff', 'tasks', 'roles.yml')

DIFFERENCE = [
    # what the lookup returns for a removal: singular grantee keys the roles role does not read
    {'role': 'admin', 'job_template': 'JT1', 'user': 'jdoe', 'state': 'absent'},
    # a declared entry, returned when include_present_state is set
    {'role': 'use', 'inventories': ['Inv1'], 'teams': ['T1'], 'state': 'present'},
    # a declared entry written with a singular resource key, so it names no resource the roles role reads
    {'role': 'use', 'credential': 'C1', 'users': ['jdoe'], 'state': 'present'},
    {'role': 'member', 'target_team': 'T2', 'state': 'absent'},
    # a declared entry written with the singular key, which the roles role can't apply either
    {'role': 'admin', 'organizations': ['O1'], 'user': 'jsmith', 'state': 'present'},
    {'role': 'admin', 'projects': ['P1'], 'users': ['jdoe'], 'state': 'present'},
]


def block():
    with open(TASKS) as f:
        tasks = yaml.safe_load(f)
    return next(t for t in tasks if 'block' in t)['block']


def first_task_setting(fact):
    return next(t for t in block() if fact in t.get('ansible.builtin.set_fact', {}))


def run_role_tasks(difference, secure_logging=False):
    """Run the set_fact and report tasks after the lookup, in order, as Ansible would."""
    facts = {'__roles_difference': difference, 'controller_configuration_object_diff_secure_logging': secure_logging}
    reports = []
    start = block().index(first_task_setting('__roles_without_grantee'))
    for t in block()[start:]:
        templar = Templar(loader=DataLoader(), variables=facts)
        # ansible-core before 2.19 renders a test result as the text 'True'/'False'
        if 'when' in t and templar.template(trust_as_template('{{ %s }}' % t['when'])) not in (True, 'True'):
            continue
        if 'ansible.builtin.set_fact' in t:
            for key, expr in t['ansible.builtin.set_fact'].items():
                facts[key] = templar.template(trust_as_template(expr))
        else:
            no_log = templar.template(trust_as_template(t['no_log'])) in (True, 'True') if 'no_log' in t else False
            if 'msg' in t['ansible.builtin.debug']:
                reports.append(('msg', templar.template(trust_as_template(t['ansible.builtin.debug']['msg'])), no_log))
            else:
                reports.append(('var', t['ansible.builtin.debug']['var'], no_log))
    return facts, reports


def test_only_entries_with_a_grantee_and_a_resource_reach_the_roles_role_in_order():
    """Entries without users or teams, or without a resource key, are set aside; both lists keep the lookup's order."""
    facts = run_role_tasks(DIFFERENCE)[0]
    assert facts['controller_roles'] == [DIFFERENCE[1], DIFFERENCE[5]]
    assert facts['__roles_without_grantee'] == [DIFFERENCE[0], DIFFERENCE[3], DIFFERENCE[4]]
    assert facts['__roles_without_resource'] == [DIFFERENCE[2]]
    assert facts['__roles_unapplied'] == [DIFFERENCE[0], DIFFERENCE[2], DIFFERENCE[3], DIFFERENCE[4]]


@pytest.mark.parametrize('secure_logging', (False, True))
def test_entries_it_cant_apply_are_counted_openly_and_listed_unless_secure_logging(secure_logging):
    """The count is always shown; the entries, which name users, are hidden under secure logging."""
    (kind, msg, msg_hidden), (list_kind, var, list_hidden) = run_role_tasks(DIFFERENCE, secure_logging)[1]
    assert kind == 'msg' and not msg_hidden
    assert ' 4 ' in msg, msg
    assert list_kind == 'var' and var == '__roles_unapplied'
    assert list_hidden is secure_logging


@pytest.mark.parametrize('difference', ([], [DIFFERENCE[1], DIFFERENCE[5]]))
def test_nothing_is_reported_when_every_entry_names_a_grantee_and_a_resource(difference):
    facts, reports = run_role_tasks(difference)
    assert facts['controller_roles'] == difference
    assert reports == []
